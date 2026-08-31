"""Сотрудники всего РУДН, а не только Инженерной академии.

Два источника на головном сайте:

* `/staff/<id>` — личная карточка (ректор, проректоры и прочее руководство);
* `/sveden/employees/pps/index.html` — обязательные сведения об
  образовательной организации: три с лишним тысячи преподавателей с
  должностями, степенями и дисциплинами.

Важно: в `robots.txt` головного сайта страница ППС закрыта
(`Disallow: /sveden/employees/pps/`), поэтому она берётся только по явному
согласию — флагом `--rudn` у скрапера, одним запросом, без обхода вглубь.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from backend.config import Settings
from backend.scraper import html as H
from backend.scraper.http import Fetcher
from backend.scraper.models import Person
from backend.scraper.parsers import EMAIL_RE, PHONE_RE
from backend.textutil import deconfuse

log = logging.getLogger(__name__)

RUDN_BASE = "https://www.rudn.ru"
PPS_PATH = "/sveden/employees/pps/index.html"

# Карточки руководства, которые имеет смысл знать киоску.
DEFAULT_STAFF_PATHS = ("/staff/1045",)

# Дисциплин у преподавателя бывает под сотню — в ответ всё равно попадут
# первые несколько, а индекс раздувать незачем.
MAX_SUBJECTS = 12
MAX_SUBJECT_CHARS = 400

_SPLIT_SUBJECTS = re.compile(r"\s*;\s*")
# Длинные списки в таблице свёрнуты кнопкой, и её подпись попадает в текст.
_UI_NOISE = re.compile(r"\s*(показать\s+(все|полностью)|свернуть|скрыть)\s*$", re.IGNORECASE)

# В таблице пустые клетки заполнены словами, а не пробелами. Хранить «Без
# ученого звания» бессмысленно: модель прочитает это как звание.
_PLACEHOLDERS = {
    "",
    "-",
    "—",
    "нет",
    "не имеет",
    "отсутствует",
    "без ученой степени",
    "без учёной степени",
    "без ученого звания",
    "без учёного звания",
}


def _value(text: str) -> str:
    return "" if text.strip().lower() in _PLACEHOLDERS else text.strip()


def parse_staff_page(tree: HTMLParser, source_url: str) -> Person | None:
    """Личная карточка сотрудника на www.rudn.ru/staff/<id>."""
    name = deconfuse(H.page_title(tree))
    if not name or len(name.split()) < 2:
        return None

    position = H.node_text(tree.css_first(".description"))
    contacts = H.node_text(tree.css_first(".contacts"))
    job = H.node_text(tree.css_first(".detail__job_info"))
    if job:
        # «Детально о работе: ректор» — оставляем только саму должность.
        job = re.sub(r"^Детально о работе:?\s*", "", job).strip()

    photo = ""
    image = tree.css_first(".avatar img") or tree.css_first("img.avatar")
    if image is not None and image.attributes.get("src"):
        photo = urljoin(source_url, image.attributes["src"])

    return Person(
        name=name,
        position=position or job,
        unit="РУДН",
        phones=sorted({m.group(0).strip() for m in PHONE_RE.finditer(contacts)}),
        emails=sorted({e.lower() for e in EMAIL_RE.findall(contacts)}),
        profile_url=source_url,
        photo_url=photo,
        source_url=source_url,
        scope="university",
    )


def parse_pps_table(tree: HTMLParser, source_url: str) -> list[Person]:
    """Таблица педагогического состава из сведений об образовательной организации.

    Колонки заданы приказом Рособрнадзора и по порядку одинаковы у всех вузов:
    номер, ФИО, должность, дисциплины, образование, степень, звание и дальше
    сведения о наградах и повышении квалификации — их в базу не берём.
    """
    table = tree.css_first("table")
    if table is None:
        return []

    people: list[Person] = []
    for row in table.css("tbody tr"):
        cells = [H.node_text(cell) for cell in row.css("td")]
        if len(cells) < 3:
            continue

        name = deconfuse(cells[1])
        if not name or len(name.split()) < 2:
            continue

        raw_subjects = _value(cells[3]) if len(cells) > 3 else ""
        subjects = _SPLIT_SUBJECTS.split(raw_subjects) if raw_subjects else []
        # Дубли вроде «Профессиональные болезни» на русском и английском.
        unique: list[str] = []
        for subject in subjects:
            subject = _UI_NOISE.sub("", subject.strip())[:MAX_SUBJECT_CHARS]
            if subject and subject not in unique:
                unique.append(subject)

        people.append(
            Person(
                name=name,
                position=_value(cells[2]),
                unit="РУДН",
                degree=_value(cells[5]) if len(cells) > 5 else "",
                academic_title=_value(cells[6]) if len(cells) > 6 else "",
                subjects=unique[:MAX_SUBJECTS],
                source_url=source_url,
                scope="university",
            )
        )
    return people


def scrape_rudn(
    settings: Settings,
    fetcher: Fetcher,
    *,
    staff_paths: tuple[str, ...] = DEFAULT_STAFF_PATHS,
    with_pps: bool = True,
) -> list[Person]:
    """Собирает сотрудников головного сайта РУДН."""
    people: list[Person] = []

    for path in staff_paths:
        url = urljoin(RUDN_BASE, path)
        page = fetcher.get(url)
        if page is None:
            continue
        person = parse_staff_page(H.parse(page.html), url)
        if person is not None:
            people.append(person)
            log.info("Карточка сотрудника РУДН: %s", person.name)

    if with_pps:
        url = urljoin(RUDN_BASE, PPS_PATH)
        page = fetcher.get(url)
        if page is None:
            log.warning("Не удалось загрузить список преподавателей %s", url)
        else:
            staff = parse_pps_table(H.parse(page.html), url)
            log.info("Преподавателей РУДН в списке: %s", len(staff))
            people.extend(staff)

    return people
