"""CLI скрапера: uv run rudik-scrape [--cache] [--max-pages N] [--index]."""

from __future__ import annotations

import argparse
import logging
import sys

from backend.config import get_settings
from backend.scraper.pipeline import run_scrape, save


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rudik-scrape",
        description="Собирает данные с academy.rudn.ru в data/documents.jsonl и data/structured.json",
    )
    parser.add_argument("--cache", action="store_true", help="использовать сохранённый HTML из data/raw")
    parser.add_argument("--max-pages", type=int, default=None, help="ограничить число страниц")
    parser.add_argument("--url", action="append", dest="seeds", help="начать обход с конкретного URL")
    parser.add_argument("--index", action="store_true", help="сразу пересобрать поисковый индекс")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    settings = get_settings()
    result = run_scrape(
        settings, use_cache=args.cache, max_pages=args.max_pages, seeds=args.seeds
    )
    stats = save(result, settings)

    print("Собрано:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"  -> {settings.documents_path}")
    print(f"  -> {settings.structured_path}")

    if args.index:
        from backend.rag.build import build_index

        info = build_index(settings)
        print("Индекс:")
        for key, value in info.items():
            print(f"  {key}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
