"""HTTP-слой скрапера: вежливые запросы + кэш сырых страниц на диске."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from backend.config import Settings

log = logging.getLogger(__name__)

SKIP_SUFFIXES = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
)


def normalize_url(url: str, base: str) -> str | None:
    """Приводит ссылку к абсолютному каноническому виду; None — если ссылку не берём."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
        return None

    absolute = urljoin(base, url)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None

    path = parts.path or "/"
    if path.lower().endswith(SKIP_SUFFIXES):
        return None
    # Схлопываем дубли слэшей и убираем хвостовой слэш (кроме корня).
    while "//" in path[1:]:
        path = path[0] + path[1:].replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Фрагменты выкидываем, значимые query-параметры (пагинация, язык программ) оставляем.
    query = parts.query
    if query:
        keep = []
        for item in query.split("&"):
            name = item.split("=", 1)[0]
            if name in ("page", "prog_lang", "tag", "level"):
                keep.append(item)
        query = "&".join(sorted(keep))

    return urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))


def url_to_filename(url: str) -> str:
    """Стабильное человекочитаемое имя файла для кэша."""
    parts = urlsplit(url)
    slug = (parts.path.strip("/") or "index").replace("/", "__")
    if parts.query:
        slug += "__" + parts.query.replace("=", "-").replace("&", "_")
    slug = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in slug)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:80]}.{digest}.html"


@dataclass
class Page:
    url: str
    html: str
    from_cache: bool


class Fetcher:
    """Синхронный загрузчик с паузами между запросами и файловым кэшем."""

    def __init__(self, settings: Settings, *, use_cache: bool = True) -> None:
        self.settings = settings
        self.use_cache = use_cache
        self.cache_dir: Path = settings.raw_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            trust_env=settings.scraper_trust_env,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.settings.crawl_delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get(self, url: str) -> Page | None:
        cache_path = self.cache_dir / url_to_filename(url)
        if self.use_cache and cache_path.exists():
            return Page(
                url=url, html=cache_path.read_text(encoding="utf-8"), from_cache=True
            )

        self._throttle()
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            log.warning("Не удалось загрузить %s: %s", url, exc)
            return None

        if response.status_code != 200:
            log.warning("%s -> HTTP %s", url, response.status_code)
            return None
        if "text/html" not in response.headers.get("content-type", ""):
            return None

        response.encoding = response.encoding or "utf-8"
        html = response.text
        cache_path.write_text(html, encoding="utf-8")
        return Page(url=url, html=html, from_cache=False)
