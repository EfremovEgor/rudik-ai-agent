"""Обход сайта в ширину по внутренним ссылкам."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from backend.config import Settings
from backend.scraper import html as H
from backend.scraper.http import Fetcher, normalize_url

log = logging.getLogger(__name__)

# Разделы сайта, которые есть в шапке — с них начинаем обход.
SEED_PATHS = (
    "/",
    "/news/",
    "/academy/administration",
    "/academy/departments",
    "/academy/contacts",
    "/academy/history",
    "/applicants/study_directions",
    "/applicants/committee",
    "/applicants/additional_education",
    "/applicants/reference",
    "/students/schedule",
    "/students/appplications",
    "/students/student_committee",
    "/science/directions",
    "/science/scientific_centers",
    "/science/events",
    "/science/journals",
    "/science/dissertation_committees",
    "/science/scientific_student_society",
    "/science/digital_library",
)

# Англоязычная версия и служебные разделы в индекс не идут.
EXCLUDE_PREFIXES = ("/en/", "/admin", "/media/", "/static/", "/accounts", "/i18n")


@dataclass
class CrawledPage:
    url: str
    path: str
    tree: HTMLParser
    depth: int


def is_internal(url: str, base: str) -> bool:
    host = urlsplit(base).netloc.lower()
    parts = urlsplit(url)
    if parts.netloc.lower() != host:
        return False
    return not parts.path.startswith(EXCLUDE_PREFIXES)


def crawl(
    settings: Settings,
    fetcher: Fetcher,
    *,
    seeds: list[str] | None = None,
    max_pages: int | None = None,
    max_depth: int = 3,
) -> Iterator[CrawledPage]:
    """Обходит сайт в ширину, отдавая разобранные страницы по мере загрузки."""
    base = settings.site_base.rstrip("/")
    limit = max_pages or settings.crawl_max_pages
    start = seeds or [base + path for path in SEED_PATHS]

    queue: deque[tuple[str, int]] = deque()
    seen: set[str] = set()
    for url in start:
        normalized = normalize_url(url, base)
        if normalized and normalized not in seen:
            seen.add(normalized)
            queue.append((normalized, 0))

    processed = 0
    while queue and processed < limit:
        url, depth = queue.popleft()
        page = fetcher.get(url)
        if page is None:
            continue

        tree = H.parse(page.html)
        outgoing = H.links(tree, url) if depth < max_depth else []
        processed += 1
        log.info("[%s/%s] d%s %s%s", processed, limit, depth, url, "" if not page.from_cache else " (cache)")

        yield CrawledPage(url=url, path=urlsplit(url).path, tree=tree, depth=depth)

        for raw in outgoing:
            normalized = normalize_url(raw, base)
            if not normalized or normalized in seen:
                continue
            if not is_internal(normalized, base):
                continue
            seen.add(normalized)
            queue.append((normalized, depth + 1))
