"""Сборка поискового индекса: uv run rudik-index."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from backend.config import Settings, get_settings
from backend.rag.documents import chunk_documents, load_documents
from backend.rag.embeddings import get_embedder
from backend.rag.index import KnowledgeBase

log = logging.getLogger(__name__)


def build_index(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    documents = load_documents(settings.documents_path)
    if not documents:
        raise SystemExit(
            f"Нет документов в {settings.documents_path}. Сначала запустите: uv run rudik-scrape"
        )

    chunks = chunk_documents(
        documents, size=settings.chunk_chars, overlap=settings.chunk_overlap
    )
    embedder = get_embedder(settings.embeddings, settings.embed_model)
    kb = KnowledgeBase.build(chunks, embedder)
    kb.save(settings.index_dir)

    from backend.rag import store

    store.reload_kb(settings)
    return {"documents": len(documents), **kb.stats()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rudik-index", description="Пересобирает индекс базы знаний")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )
    info = build_index()
    for key, value in info.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
