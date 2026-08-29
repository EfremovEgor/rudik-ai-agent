"""Парсеры конкретных типов страниц academy.rudn.ru."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

from backend.scraper import html as H
from backend.scraper.models import Department, NewsItem, Person, Program
from backend.textutil import deconfuse

ROOM_RE = re.compile(
    r"каб(?:\.|инет)?\s*№?\s*([\d/\-АБВГабвг]+(?:\s*[,и]\s*[\d/\-АБВГабвг]+)*)", re.I
)
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d\)?")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
CODE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2})\b")


def extract_rooms(text: str) -> list[str]:
    """Вытаскивает номера кабинетов: "каб. 404, 204" -> ["404", "204"]."""
    rooms: list[str] = []
    for match in ROOM_RE.finditer(text):
        for part in re.split(r"[,и]", match.group(1)):
            part = part.strip()
            # Номер кабинета обязан содержать цифру: "д. 3" и прочий адрес отсекаем.
            if part and any(ch.isdigit() for ch in part) and part not in rooms:
                rooms.append(part)
    return rooms


# --------------------------------------------------------------------------- люди


def parse_employee_cards(tree: HTMLParser, source_url: str, unit: str = "") -> list[Person]:
    """Карточки сотрудников (article.employee-card) — дирекция, кафедры, отделы."""
    people: list[Person] = []
    for card in tree.css("article.employee-card, .employee-card"):
        person = _employee_card_to_person(card, source_url, unit)
        if person is not None:
            people.append(person)
    return people


def _employee_card_to_person(card: Node, source_url: str, unit: str) -> Person | None:
    name_node = card.css_first("h3 a") or card.css_first("h3") or card.css_first("h4")
    name = deconfuse(H.node_text(name_node))
    if not name or len(name.split()) < 2:
        return None

    profile_url = ""
    link = card.css_first("h3 a[href]")
    if link is not None:
        profile_url = urljoin(source_url, link.attributes.get("href", ""))

    meta_nodes = card.css(".uk-comment-meta li") or card.css(".uk-comment-meta")
    position = "; ".join(filter(None, (H.node_text(n) for n in meta_nodes)))

    body = card.css_first(".uk-comment-body")
    address, phones, emails = "", [], []
    if body is not None:
        for item in body.css("li"):
            text = H.node_text(item)
            if not text:
                continue
            icon = item.css_first("[uk-icon]")
            kind = (icon.attributes.get("uk-icon") if icon is not None else "") or ""
            if "mail" in kind or EMAIL_RE.search(text):
                emails.extend(EMAIL_RE.findall(text))
            elif "receiver" in kind or "phone" in kind:
                phones.extend(m.group(0).strip() for m in PHONE_RE.finditer(text))
            elif "location" in kind or "каб" in text.lower() or "ул." in text:
                address = text
            else:
                emails.extend(EMAIL_RE.findall(text))

    photo = ""
    img = card.css_first("img")
    if img is not None and img.attributes.get("src"):
        photo = urljoin(source_url, img.attributes["src"])

    return Person(
        name=name,
        position=position,
        unit=unit,
        address=address,
        rooms=extract_rooms(address),
        phones=sorted(set(phones)),
        emails=sorted({e.lower() for e in emails}),
        profile_url=profile_url,
        photo_url=photo,
        source_url=source_url,
    )


def parse_profile(tree: HTMLParser, source_url: str) -> Person | None:
    """Личная страница сотрудника /profile/N."""
    container = tree.css_first(".container-employee") or tree.css_first(".profile_content")
    if container is None:
        return None
    name = deconfuse(
        H.node_text(
            container.css_first("h1")
            or container.css_first("h2")
            or tree.css_first(".page-name")
        )
    )
    if not name:
        return None
    text = H.to_markdown(container, source_url)
    position = H.node_text(container.css_first(".job-title"))
    address = next((line for line in text.splitlines() if "каб" in line.lower()), "")
    return Person(
        name=name,
        position=position,
        address=address,
        rooms=extract_rooms(text),
        phones=sorted({m.group(0).strip() for m in PHONE_RE.finditer(text)}),
        emails=sorted({e.lower() for e in EMAIL_RE.findall(text)}),
        profile_url=source_url,
        source_url=source_url,
    )


# ---------------------------------------------------------------------- кафедры


def parse_departments(tree: HTMLParser, source_url: str) -> list[Department]:
    """Страница /academy/departments — сетка карточек кафедр."""
    departments: list[Department] = []
    for card in tree.css(".direction_info-card"):
        text_block = card.css_first(".department-text")
        if text_block is None:
            continue
        name = H.node_text(text_block.css_first("h3"))
        if not name:
            continue
        link = text_block.css_first("a[href]")
        url = urljoin(source_url, link.attributes.get("href", "")) if link is not None else ""

        description = H.node_text(text_block)
        description = description.replace(name, "", 1).replace("Подробнее", "").strip()

        head, head_position, contacts = "", "", []
        head_card = card.css_first("article.employee-card, .employee-card")
        if head_card is not None:
            person = _employee_card_to_person(head_card, source_url, unit=name)
            if person is not None:
                head = person.name
                head_position = person.position
                contacts = [*person.phones, *person.emails, person.address]

        departments.append(
            Department(
                name=name,
                url=url,
                slug=urlsplit(url).path.rsplit("/", 1)[-1] if url else "",
                description=description,
                head=head,
                head_position=head_position,
                contacts=[c for c in contacts if c],
            )
        )
    return departments


def parse_department_page(tree: HTMLParser, source_url: str) -> tuple[Department, list[Person]]:
    """Страница отдельной кафедры: описание, направления и состав."""
    name = H.page_title(tree)
    main = H.main_content(tree)
    info = tree.css_first(".info-block")
    description = H.node_text(info) if info is not None else ""

    programs: list[str] = []
    for node in tree.css(".naprs li, .levels-accordion li, .level-accordion li"):
        text = H.node_text(node)
        if text and len(text) > 8:
            programs.append(text)

    people = parse_employee_cards(tree, source_url, unit=name)
    department = Department(
        name=name,
        url=source_url,
        slug=urlsplit(source_url).path.rsplit("/", 1)[-1],
        description=description or H.node_text(main)[:800],
        programs=programs[:40],
    )
    if people:
        department.head = people[0].name
        department.head_position = people[0].position
    return department, people


# ---------------------------------------------------------------------- новости


def parse_news_list(tree: HTMLParser, source_url: str) -> list[NewsItem]:
    """Карточки на странице /news/."""
    items: list[NewsItem] = []
    for card in tree.css(".news-card-container"):
        link = card.css_first("a[href]")
        if link is None:
            continue
        url = urljoin(source_url, link.attributes.get("href", ""))
        title = H.node_text(card.css_first(".news-title"))
        badge = H.node_text(card.css_first(".uk-card-badge")) or ""
        date_match = DATE_RE.search(badge)
        if title:
            items.append(
                NewsItem(title=title, url=url, date=date_match.group(1) if date_match else badge)
            )
    return items


def parse_news_item(tree: HTMLParser, source_url: str) -> NewsItem | None:
    """Страница одной новости /news/N."""
    title = H.page_title(tree)
    if not title:
        return None
    body_node = tree.css_first(".news_content") or H.main_content(tree)
    body = H.to_markdown(body_node, source_url)
    raw_date = H.node_text(tree.css_first(".news-items-date")) or ""
    match = DATE_RE.search(raw_date or body[:400])
    tags = [H.node_text(n).lstrip("#") for n in tree.css(".hashtags a, .hashtags span")]
    return NewsItem(
        title=title,
        url=source_url,
        date=match.group(1) if match else raw_date,
        tags=[t for t in tags if t],
        body=body,
    )


# ------------------------------------------------------------------ направления


LEVEL_NAMES = ("бакалавриат", "специалитет", "магистратура", "аспирантура")


def parse_level_page(tree: HTMLParser, source_url: str, level: str = "") -> list[Program]:
    """Список направлений на /applicants/study_directions/{bachelor,masters,postgraduates}.

    Разметка — аккордеон: заголовок это укрупнённое направление с кодом,
    внутри — ссылки на профили (образовательные программы).
    """
    programs: list[Program] = []
    language = "en" if "prog_lang=en" in source_url else "ru"

    for item in tree.css(".naprs li"):
        heading = H.node_text(item.css_first(".uk-accordion-title"))
        if not heading:
            continue
        code_match = CODE_RE.search(heading)
        direction = CODE_RE.sub("", heading).strip(" -—:«»\"")

        profiles = item.css(".uk-accordion-content a[href]")
        if not profiles:
            programs.append(
                Program(
                    title=direction,
                    url=source_url,
                    level=level,
                    code=code_match.group(1) if code_match else "",
                    language=language,
                )
            )
            continue

        for profile in profiles:
            name = H.node_text(profile)
            name = re.sub(r"^\s*профил[ья]\s*:?\s*", "", name, flags=re.I).strip()
            if not name:
                continue
            programs.append(
                Program(
                    title=name,
                    url=urljoin(source_url, profile.attributes.get("href", "")),
                    level=level,
                    code=code_match.group(1) if code_match else "",
                    language=language,
                    description=f"Направление: {direction}.",
                )
            )
    return programs


def parse_program_page(tree: HTMLParser, source_url: str) -> Program | None:
    """Страница одной образовательной программы /applicants/study_directions/N."""
    title = H.page_title(tree)
    if not title:
        return None
    text = H.to_markdown(H.main_content(tree), source_url)
    head = text[:400].lower()

    level = next((name for name in LEVEL_NAMES if name in head), "")
    code_match = CODE_RE.search(text)
    department_match = re.search(r"Кафедра\s+([^\n#]{3,80})", text)

    return Program(
        title=title,
        url=source_url,
        level=level,
        code=code_match.group(1) if code_match else "",
        language="en" if "prog_lang=en" in source_url else "ru",
        department=("Кафедра " + department_match.group(1).strip()) if department_match else "",
        description=text[:2500],
    )
