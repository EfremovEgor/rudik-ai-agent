"""Плотные эмбеддинги для гибридного поиска.

По умолчанию используется fastembed (ONNX, мультиязычная модель E5 — хорошо
понимает русский, не тянет torch). Если пакет не установлен, RAG автоматически
падает обратно на разреженный поиск: BM25 работает и без векторов.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str
    dim: int

    def encode_documents(self, texts: list[str]) -> np.ndarray: ...

    def encode_query(self, text: str) -> np.ndarray: ...


class FastEmbedEmbedder:
    """Обёртка над fastembed. E5-модели требуют префиксов query:/passage:."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        from fastembed import TextEmbedding

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name)
        self.dim = len(next(iter(self._model.embed(["проверка"]))))
        self._is_e5 = "e5" in model_name.lower()

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(list(self._model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-9, None)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        prepared = [f"passage: {t}" for t in texts] if self._is_e5 else texts
        return self._embed(prepared)

    def encode_query(self, text: str) -> np.ndarray:
        prepared = f"query: {text}" if self._is_e5 else text
        return self._embed([prepared])[0]


def get_embedder(kind: str, model_name: str) -> Embedder | None:
    """Возвращает эмбеддер или None, если плотный поиск недоступен."""
    if kind in ("none", "hash", "off"):
        return None
    try:
        return FastEmbedEmbedder(model_name)
    except ImportError:
        log.warning(
            "fastembed не установлен — работает только BM25. "
            "Поставьте зависимости: uv sync --extra rag"
        )
    except Exception:
        log.exception("Не удалось загрузить модель эмбеддингов %s", model_name)
    return None
