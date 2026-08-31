"""Полный проход скрапинга: обход сайта -> структурированные данные -> документы для RAG."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.config import Settings, get_settings
from backend.scraper import html as H
from backend.scraper import parsers as P
from backend.scraper.crawl import CrawledPage, crawl
from backend.scraper.http import Fetcher
from backend.scraper.models import Department, NewsItem, Person, Program
from backend.textutil import name_key

log = logging.getLogger(__name__)

SECTION_TITLES = {
    "academy": "Об академии",
    "applicants": "Абитуриентам",
    "students": "Студентам",
    "science": "Наука",
    "news": "Новости",
    "profile": "Сотрудники",
}


def normalize_name(name: str) -> str:
    return name_key(name)


def section_of(path: str) -> str:
    head = path.strip("/").split("/")[0] if path.strip("/") else "main"
    return SECTION_TITLES.get(head, "Главная" if head == "main" else head)


@dataclass
class ScrapeResult:
    people: dict[str, Person] = field(default_factory=dict)
    departments: dict[str, Department] = field(default_factory=dict)
    news: dict[str, NewsItem] = field(default_factory=dict)
    programs: dict[str, Program] = field(default_factory=dict)
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_person(self, person: Person) -> None:
        key = normalize_name(person.name)
        if not key:
            return
        existing = self.people.get(key)
        if existing is None:
            self.people[key] = person
        else:
            existing.merge(person)

    def summary(self) -> dict[str, int]:
        return {
            "people": len(self.people),
            "departments": len(self.departments),
            "news": len(self.news),
            "programs": len(self.programs),
            "pages": len(self.pages),
        }


def handle_page(page: CrawledPage, result: ScrapeResult) -> None:
    """Раскладывает страницу по нужному парсеру и всегда сохраняет её текст."""
    path = page.path
    tree = page.tree
    url = page.url

    # Ссылки уже собраны обходчиком, теперь можно выкинуть шапку/футер.
    H.clean(tree)
    title = H.page_title(tree) or path

    if path.startswith("/profile/"):
        person = P.parse_profile(tree, url)
        if person is not None:
            result.add_person(person)

    elif path == "/academy/administration":
        for person in P.parse_employee_cards(
            tree, url, unit="Дирекция Инженерной академии"
        ):
            result.add_person(person)

    elif path == "/academy/departments":
        for department in P.parse_departments(tree, url):
            result.departments.setdefault(department.name, department)

    elif path.startswith("/academy/departments/"):
        department, people = P.parse_department_page(tree, url)
        if department.name:
            existing = result.departments.get(department.name)
            if existing is None:
                result.departments[department.name] = department
            else:
                existing.url = existing.url or department.url
                existing.programs = existing.programs or department.programs
                existing.description = existing.description or department.description
        for person in people:
            result.add_person(person)

    elif re.fullmatch(r"/news/\d+", path):
        item = P.parse_news_item(tree, url)
        if item is not None:
            result.news[url] = item

    elif path.rstrip("/") == "/news":
        for item in P.parse_news_list(tree, url):
            result.news.setdefault(item.url, item)

    elif re.fullmatch(r"/applicants/study_directions/\d+", path):
        program = P.parse_program_page(tree, url)
        if program is not None:
            result.programs[program.url] = program

    elif path.startswith("/applicants/study_directions"):
        level = path.rsplit("/", 1)[-1] if path.count("/") > 2 else ""
        level_name = {
            "bachelor": "бакалавриат/специалитет",
            "masters": "магистратура",
            "postgraduates": "аспирантура",
        }.get(level, "")
        for program in P.parse_level_page(tree, url, level=level_name):
            existing = result.programs.get(program.url)
            if existing is None:
                result.programs[program.url] = program
            else:
                # Страница уровня знает уровень и код точнее, чем страница программы.
                existing.level = existing.level or program.level
                existing.code = existing.code or program.code

    else:
        for person in P.parse_employee_cards(tree, url, unit=title):
            result.add_person(person)

    # То, что уже стало отдельной сущностью, не дублируем документом-страницей.
    if (
        path.rstrip("/") == "/news"
        or path.startswith("/news/")
        or path.startswith("/profile/")
        or re.fullmatch(r"/applicants/study_directions/\d+", path)
    ):
        return

    text = H.to_markdown(H.main_content(tree), url)
    if len(text) > 120:
        result.pages[url] = {
            "url": url,
            "title": title,
            "section": section_of(path),
            "text": text,
        }


def run_scrape(
    settings: Settings | None = None,
    *,
    use_cache: bool = False,
    max_pages: int | None = None,
    seeds: list[str] | None = None,
    with_rudn: bool = False,
) -> ScrapeResult:
    settings = settings or get_settings()
    result = ScrapeResult()
    with Fetcher(settings, use_cache=use_cache) as fetcher:
        for page in crawl(settings, fetcher, seeds=seeds, max_pages=max_pages):
            try:
                handle_page(page, result)
            except Exception:  # одна кривая страница не должна ронять весь обход
                log.exception("Ошибка разбора %s", page.url)

        # Сотрудников головного РУДН добавляем последними: карточки академии
        # уже в результате, и общий список только дополнит их степенями
        # и дисциплинами, не затирая кабинеты и телефоны.
        if with_rudn:
            from backend.scraper.rudn import scrape_rudn

            try:
                for person in scrape_rudn(settings, fetcher):
                    result.add_person(person)
            except Exception:
                log.exception("Не удалось собрать сотрудников РУДН")
    return result


# --------------------------------------------------------------- сохранение


# Адрес на сайте разбросан по карточкам сотрудников: «Москва, ул. Орджоникидзе,
# д. 3, каб. 403». Отдельной записи про сам адрес академии нет.
_ADDRESS = re.compile(r"Москва,\s*ул\.\s*([^,]{3,40}?),\s*д\.?\s*(\d+)", re.IGNORECASE)


def academy_card(result: ScrapeResult) -> dict[str, Any] | None:
    """Короткая карточка про саму академию: где она находится.

    На вопрос «где находится академия» поиск возвращал чьи-то профили, и модель
    придумывала адрес. Берём самый частый адрес из собранных страниц — так
    запись переживёт переезд, в отличие от вписанной руками константы.
    """
    counter: Counter[tuple[str, str]] = Counter()
    for person in result.people.values():
        counter.update(_ADDRESS.findall(person.address or ""))
    for page in result.pages.values():
        counter.update(_ADDRESS.findall(page.get("text", "")))
    if not counter:
        return None

    (street, house), _ = counter.most_common(1)[0]
    address = f"Москва, улица {street.strip()}, дом {house}"
    contacts = next(
        (url for url in result.pages if url.rstrip("/").endswith("contacts")),
        f"{get_settings().site_base}/academy/contacts",
    )
    return {
        "id": "page:academy-address",
        "kind": "page",
        "title": "Адрес Инженерной академии РУДН",
        "url": contacts,
        "section": "Об академии",
        # Формулировки вопросов оставляем в тексте: по ним словарный поиск
        # и находит эту запись, а не карточку случайного сотрудника.
        "text": (
            "Адрес Инженерной академии РУДН.\n\n"
            f"Инженерная академия РУДН находится по адресу: {address}.\n"
            "Где находится Инженерная академия, где расположена академия, "
            "как найти академию, адрес академии, куда приезжать."
        ),
        "meta": {"address": address},
    }


def build_documents(result: ScrapeResult) -> list[dict[str, Any]]:
    """Превращает результат обхода в плоский список документов для индекса."""
    documents: list[dict[str, Any]] = []

    for key, person in sorted(result.people.items()):
        documents.append(
            {
                "id": f"person:{key}",
                "kind": "person",
                "title": person.name,
                "url": person.source_url or person.profile_url,
                "section": "Сотрудники",
                "text": person.to_text(),
                "meta": person.dict(),
            }
        )

    for name, department in sorted(result.departments.items()):
        documents.append(
            {
                "id": f"department:{department.slug or normalize_name(name)}",
                "kind": "department",
                "title": name,
                "url": department.url,
                "section": "Кафедры",
                "text": department.to_text(),
                "meta": department.dict(),
            }
        )

    for url, item in result.news.items():
        documents.append(
            {
                "id": f"news:{url}",
                "kind": "news",
                "title": item.title,
                "url": url,
                "section": "Новости",
                "date": item.date,
                "text": item.to_text(),
                "meta": {"date": item.date, "tags": item.tags},
            }
        )

    for key, program in result.programs.items():
        documents.append(
            {
                "id": f"program:{key}",
                "kind": "program",
                "title": program.title,
                "url": program.url,
                "section": "Направления подготовки",
                "text": program.to_text(),
                "meta": program.dict(),
            }
        )

    card = academy_card(result)
    if card:
        documents.append(card)

    for url, page in result.pages.items():
        documents.append(
            {
                "id": f"page:{url}",
                "kind": "page",
                "title": page["title"],
                "url": url,
                "section": page["section"],
                "text": f"{page['title']}\n\n{page['text']}",
                "meta": {},
            }
        )

    return documents


def save(result: ScrapeResult, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    documents = build_documents(result)

    with settings.documents_path.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(document, ensure_ascii=False) + "\n")

    structured = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": settings.site_base,
        "counts": result.summary(),
        "people": [person.dict() for person in result.people.values()],
        "departments": [d.dict() for d in result.departments.values()],
        "news": [n.dict() for n in result.news.values()],
        "programs": [p.dict() for p in result.programs.values()],
    }
    settings.structured_path.write_text(
        json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"documents": len(documents), **result.summary()}
