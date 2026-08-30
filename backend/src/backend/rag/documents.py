"""Загрузка документов скрапера и нарезка их на фрагменты для поиска."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Короткие карточки не режем: они и так атомарные ответы.
WHOLE_KINDS = {"person", "department", "program"}


@dataclass
class Chunk:
    id: str
    doc_id: str
    kind: str
    title: str
    url: str
    section: str
    text: str
    date: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "section": self.section,
            "text": self.text,
            "date": self.date,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chunk:
        return cls(
            id=data["id"],
            doc_id=data["doc_id"],
            kind=data["kind"],
            title=data.get("title", ""),
            url=data.get("url", ""),
            section=data.get("section", ""),
            text=data.get("text", ""),
            date=data.get("date", ""),
            meta=data.get("meta", {}),
        )

    def embedding_text(self) -> str:
        """Текст, который реально уходит в эмбеддинг/BM25 — с заголовком для контекста."""
        header = " / ".join(x for x in (self.section, self.title) if x)
        return f"{header}\n{self.text}" if header else self.text


def load_documents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    documents = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                documents.append(json.loads(line))
    return documents


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Режет текст по абзацам, стараясь не рвать предложения."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), size - overlap):
                chunks.append(paragraph[start : start + size])
            continue
        if len(current) + len(paragraph) + 2 <= size:
            current = f"{current}\n\n{paragraph}" if current else paragraph
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph

    if current:
        chunks.append(current)
    return chunks or [text]


def chunk_documents(
    documents: Iterable[dict[str, Any]], *, size: int = 1200, overlap: int = 200
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        text = (document.get("text") or "").strip()
        if not text:
            continue
        kind = document.get("kind", "page")
        parts = (
            [text]
            if kind in WHOLE_KINDS or len(text) <= size
            else split_text(text, size, overlap)
        )

        for position, part in enumerate(parts):
            chunks.append(
                Chunk(
                    id=f"{document['id']}#{position}",
                    doc_id=document["id"],
                    kind=kind,
                    title=document.get("title", ""),
                    url=document.get("url", ""),
                    section=document.get("section", ""),
                    text=part,
                    date=document.get("date", ""),
                    meta=document.get("meta", {}),
                )
            )
    return chunks
