"""Единая точка доступа к базе знаний для API и инструментов агента."""

from __future__ import annotations

import logging
import threading

from backend.config import Settings, get_settings
from backend.rag.embeddings import get_embedder
from backend.rag.index import KnowledgeBase

log = logging.getLogger(__name__)

_lock = threading.Lock()
_kb: KnowledgeBase | None = None


def get_kb(settings: Settings | None = None) -> KnowledgeBase:
    """Лениво загружает индекс с диска (потокобезопасно, один раз на процесс)."""
    global _kb
    if _kb is not None:
        return _kb
    with _lock:
        if _kb is None:
            settings = settings or get_settings()
            embedder = get_embedder(settings.embeddings, settings.embed_model)
            loaded = KnowledgeBase.load(settings.index_dir, embedder)
            if loaded is None:
                log.warning(
                    "Индекс не найден в %s. Соберите его: uv run rudik-scrape --index",
                    settings.index_dir,
                )
                loaded = KnowledgeBase([], embedder=embedder)
            _kb = loaded
    return _kb


def reload_kb(settings: Settings | None = None) -> KnowledgeBase:
    """Сбрасывает кэш — вызывается после переиндексации."""
    global _kb
    with _lock:
        _kb = None
    return get_kb(settings)
