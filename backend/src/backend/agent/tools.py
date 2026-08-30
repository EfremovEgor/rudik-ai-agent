"""Инструменты агента: поиск по базе знаний академии."""

from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import urlsplit

from langchain_core.tools import tool

from backend.config import get_settings
from backend.rag.store import get_kb

log = logging.getLogger(__name__)

KindLiteral = Literal["person", "department", "news", "program", "page", "any"]


def _format_hits(hits: list, limit_chars: int = 900) -> str:
    if not hits:
        return "Ничего не найдено."
    blocks = []
    for hit in hits:
        chunk = hit.chunk
        text = chunk.text.strip()
        if len(text) > limit_chars:
            text = text[:limit_chars].rsplit(" ", 1)[0] + "..."
        header = " — ".join(x for x in (chunk.section, chunk.title) if x)
        blocks.append(f"[{header}]\n{text}\nИсточник: {chunk.url}")
    return "\n\n".join(blocks)


@tool(parse_docstring=False)
def search_academy(query: str, kind: KindLiteral = "any") -> str:
    """Ищет информацию об Инженерной академии РУДН в базе знаний сайта academy.rudn.ru.

    Подходит для вопросов про поступление, кафедры, направления подготовки,
    науку, студенческую жизнь, контакты и расписание.

    Аргументы:
        query: вопрос или ключевые слова на русском языке.
        kind: ограничить тип записей — person, department, news, program, page или any.
    """
    kb = get_kb()
    kinds = None if kind == "any" else [kind]
    hits = kb.search(query, k=get_settings().top_k, kinds=kinds)
    return _format_hits(hits)


@tool(parse_docstring=False)
def find_person(name: str) -> str:
    """Находит сотрудника академии по фамилии или должности.

    Возвращает должность, кабинет, телефон, почту и ссылку на страницу.
    Фамилию можно передавать в любом падеже: «Салтыковой», «Салтыкова».

    Аргументы:
        name: фамилия, ФИО или должность («заместитель директора по науке»).
    """
    kb = get_kb()
    people = kb.find_people(name, limit=4)
    if not people:
        hits = kb.search(name, k=3, kinds=["person"])
        if not hits:
            return f"Сотрудник «{name}» в базе не найден."
        return _format_hits(hits)

    blocks = []
    for person in people:
        lines = [person.get("name", "")]
        if person.get("position"):
            lines.append(f"Должность: {person['position']}")
        if person.get("unit"):
            lines.append(f"Подразделение: {person['unit']}")
        if person.get("rooms"):
            lines.append(f"Кабинет: {', '.join(person['rooms'])}")
        if person.get("address"):
            lines.append(f"Адрес: {person['address']}")
        if person.get("phones"):
            lines.append(f"Телефон: {', '.join(person['phones'])}")
        if person.get("emails"):
            lines.append(f"Почта: {', '.join(person['emails'])}")
        source = person.get("source_url") or person.get("profile_url") or ""
        if source:
            lines.append(f"Источник: {source}")
        blocks.append("\n".join(line for line in lines if line))
    return "\n\n".join(blocks)


@tool(parse_docstring=False)
def latest_news(limit: int = 5, tag: str = "") -> str:
    """Возвращает свежие новости и анонсы мероприятий Инженерной академии.

    Аргументы:
        limit: сколько новостей вернуть (1–10).
        tag: необязательный фильтр по теме, например «наука» или «конференция».
    """
    kb = get_kb()
    items = kb.latest_news(limit=max(1, min(limit, 10)), tag=tag or None)
    if not items:
        return "Новостей не найдено."
    return "\n\n".join(
        f"{item['date']} — {item['title']}\n{item['text']}\nИсточник: {item['url']}"
        for item in items
    )


@tool(parse_docstring=False)
def list_departments() -> str:
    """Перечисляет кафедры Инженерной академии РУДН с заведующими и ссылками."""
    kb = get_kb()
    chunks = kb.by_kind("department")
    if not chunks:
        return "Список кафедр пуст — база знаний не собрана."
    lines = []
    for chunk in chunks:
        meta = chunk.meta or {}
        head = f", заведующий: {meta['head']}" if meta.get("head") else ""
        lines.append(
            f"{chunk.title}{head}. Источник: {chunk.url or meta.get('url', '')}"
        )
    return "\n".join(lines)


@tool(parse_docstring=False)
def list_programs(level: str = "") -> str:
    """Перечисляет направления подготовки.

    Аргументы:
        level: уровень образования — «бакалавриат», «магистратура» или «аспирантура».
    """
    kb = get_kb()
    chunks = kb.by_kind("program")
    if not chunks:
        return "Направления подготовки не найдены в базе."
    needle = level.lower().strip()
    lines = []
    for chunk in chunks:
        meta = chunk.meta or {}
        chunk_level = (meta.get("level") or "").lower()
        if needle and needle[:6] not in chunk_level:
            continue
        code = f"{meta.get('code')} " if meta.get("code") else ""
        lines.append(
            f"{code}{chunk.title} ({chunk_level or 'уровень не указан'}) — {chunk.url}"
        )
    return "\n".join(lines[:60]) or f"Для уровня «{level}» направлений не найдено."


@tool(parse_docstring=False)
def open_page(url: str) -> str:
    """Загружает страницу сайта academy.rudn.ru и возвращает её текст.

    Нужен, когда информации из базы знаний не хватает или она могла устареть.

    Аргументы:
        url: полный адрес страницы на academy.rudn.ru.
    """
    settings = get_settings()
    allowed_host = urlsplit(settings.site_base).netloc
    if urlsplit(url).netloc != allowed_host:
        return f"Можно открывать только страницы сайта {allowed_host}."

    from backend.scraper import html as H
    from backend.scraper.http import Fetcher

    with Fetcher(settings, use_cache=False) as fetcher:
        page = fetcher.get(url)
    if page is None:
        return f"Страница {url} недоступна."

    tree = H.clean(H.parse(page.html))
    text = H.to_markdown(H.main_content(tree), url)
    if len(text) > 5000:
        text = text[:5000] + "..."
    return f"{H.page_title(tree)}\n\n{text}\n\nИсточник: {url}"


ALL_TOOLS = [
    search_academy,
    find_person,
    latest_news,
    list_departments,
    list_programs,
    open_page,
]
