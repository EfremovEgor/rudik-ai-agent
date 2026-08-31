"""Гибридный поиск по базе знаний: BM25 + плотные векторы, слияние по RRF."""

from __future__ import annotations

import difflib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from backend.rag.documents import Chunk
from backend.rag.embeddings import Embedder
from backend.textutil import fold, search_tokens, stem, tokenize

log = logging.getLogger(__name__)

RRF_K = 60

# Насколько ниже лучшего совпадения фамилия ещё считается равноценной.
# 0.05 покрывает разницу между точным совпадением и совпадением по основе
# (падеж), но не пускает наверх однофамильцев с явно худшим счётом.
SCOPE_BAND = 0.05

# Слова, которые не могут быть фамилией, но часто приезжают вместе с вопросом.
QUESTION_WORDS = frozenset(
    ["скажи", "скажите", "подскажи", "подскажите", "найди", "найти", "где", "какой", "какая", "какие", "какого", "кабинет", "кабинете", "аудитория", "номер", "телефон", "почта", "email", "адрес", "сидит", "сидят", "находится", "находятся", "работает", "работают", "человек", "сотрудник", "сотрудника", "пожалуйста", "рудик", "привет", "здравствуйте", "нужен", "нужна", "нужно", "зовут", "можно"]
)


@dataclass
class SearchHit:
    chunk: Chunk
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.chunk.title,
            "url": self.chunk.url,
            "section": self.chunk.section,
            "kind": self.chunk.kind,
            "date": self.chunk.date,
            "text": self.chunk.text,
            "score": round(self.score, 4),
        }


def _parse_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%d.%m.%Y")
    except (ValueError, TypeError):
        return datetime.min


class KnowledgeBase:
    """Индекс в памяти: для нескольких тысяч фрагментов этого более чем достаточно."""

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        dense: np.ndarray | None = None,
        embedder: Embedder | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.chunks = chunks
        self.dense = dense
        self.embedder = embedder
        self.meta = meta or {}
        self._bm25 = (
            BM25Okapi([search_tokens(c.embedding_text()) for c in chunks])
            if chunks
            else None
        )
        self._people = [c for c in chunks if c.kind == "person"]

    # ------------------------------------------------------------- построение

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder | None) -> KnowledgeBase:
        dense = None
        meta: dict[str, Any] = {
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "chunks": len(chunks),
            "embedder": None,
        }
        if embedder is not None and chunks:
            log.info("Считаю эмбеддинги для %s фрагментов...", len(chunks))
            dense = embedder.encode_documents([c.embedding_text() for c in chunks])
            meta["embedder"] = embedder.name
            meta["dim"] = int(dense.shape[1])
        return cls(chunks, dense=dense, embedder=embedder, meta=meta)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "chunks.jsonl").open("w", encoding="utf-8") as handle:
            for chunk in self.chunks:
                handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
        if self.dense is not None:
            np.save(directory / "dense.npy", self.dense)
        elif (directory / "dense.npy").exists():
            (directory / "dense.npy").unlink()
        (directory / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, directory: Path, embedder: Embedder | None) -> KnowledgeBase | None:
        chunks_path = directory / "chunks.jsonl"
        if not chunks_path.exists():
            return None
        chunks = [
            Chunk.from_dict(json.loads(line))
            for line in chunks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        meta = {}
        meta_path = directory / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        dense = None
        dense_path = directory / "dense.npy"
        if dense_path.exists() and embedder is not None:
            candidate = np.load(dense_path)
            if candidate.shape[0] == len(chunks) and candidate.shape[1] == embedder.dim:
                dense = candidate
            else:
                log.warning(
                    "Векторный индекс не совпадает с моделью — пересоберите индекс"
                )
        return cls(chunks, dense=dense, embedder=embedder, meta=meta)

    # ----------------------------------------------------------------- поиск

    def search(
        self,
        query: str,
        *,
        k: int = 6,
        kinds: Iterable[str] | None = None,
    ) -> list[SearchHit]:
        if not self.chunks or not query.strip():
            return []

        allowed = set(kinds) if kinds else None
        candidates = [
            i for i, c in enumerate(self.chunks) if allowed is None or c.kind in allowed
        ]
        if not candidates:
            return []

        pool = max(k * 5, 30)
        ranks: dict[int, dict[str, int]] = {}

        if self._bm25 is not None:
            scores = self._bm25.get_scores(search_tokens(query))
            ordered = sorted(candidates, key=lambda i: -scores[i])[:pool]
            for rank, index in enumerate(ordered):
                if scores[index] > 0:
                    ranks.setdefault(index, {})["lexical"] = rank

        if self.dense is not None and self.embedder is not None:
            vector = self.embedder.encode_query(query)
            similarity = self.dense @ vector
            ordered = sorted(candidates, key=lambda i: -similarity[i])[:pool]
            for rank, index in enumerate(ordered):
                ranks.setdefault(index, {})["dense"] = rank

        fused: list[SearchHit] = []
        for index, entry in ranks.items():
            score = sum(1.0 / (RRF_K + rank) for rank in entry.values())
            fused.append(
                SearchHit(
                    chunk=self.chunks[index],
                    score=score,
                    lexical_rank=entry.get("lexical"),
                    dense_rank=entry.get("dense"),
                )
            )
        fused.sort(key=lambda hit: -hit.score)

        # Не отдаём весь топ одной странице — разнообразие источников важнее.
        per_document: dict[str, int] = {}
        diverse: list[SearchHit] = []
        for hit in fused:
            count = per_document.get(hit.chunk.doc_id, 0)
            if count >= 2:
                continue
            per_document[hit.chunk.doc_id] = count + 1
            diverse.append(hit)
            if len(diverse) == k:
                break
        return diverse

    # --------------------------------------------------------- люди и разделы

    def find_people(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Поиск сотрудника по фамилии в любом падеже ("Салтыковой" -> "Салтыкова").

        Модель иногда передаёт сюда всю реплику целиком, поэтому служебные слова
        вопроса отбрасываем: иначе «скажи» или «кабинет» случайно совпадут
        с чьим-нибудь именем и вытянут не того человека.
        """
        # tokenize отрезает знаки препинания: "солтыковой." иначе не сматчится.
        raw = tokenize(query)
        words = [w for w in raw if len(w) > 3 and w not in QUESTION_WORDS]
        # Распознавание речи иногда рвёт длинную фамилию надвое
        # («Дмитри Ченкова»), поэтому пробуем и склеенные соседние слова.
        words += [
            raw[i] + raw[i + 1]
            for i in range(len(raw) - 1)
            if len(raw[i] + raw[i + 1]) > 8
        ]
        if not words:
            return []

        # Стеммы гасят падежи: «Салтыковой» и «Салтыкова» дают одну основу.
        word_stems = [(word, stem(word)) for word in words]

        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in self._people:
            meta = chunk.meta or {}
            name = fold(meta.get("name") or chunk.title)
            parts = [(part, stem(part)) for part in name.split()]
            best = 0.0
            for word, word_stem in word_stems:
                for position, (part, part_stem) in enumerate(parts):
                    if part == word or part_stem == word_stem:
                        score = 1.0 if part == word else 0.97
                    else:
                        score = max(
                            difflib.SequenceMatcher(None, word, part).ratio(),
                            difflib.SequenceMatcher(None, word_stem, part_stem).ratio()
                            * 0.98,
                        )
                    # Спрашивают по фамилии; совпадение только по имени или
                    # отчеству («Светлана Владимировна») почти ничего не значит.
                    if position > 0:
                        score *= 0.75
                    best = max(best, score)
            # Совпадение по должности тоже засчитываем, но слабее.
            if best < 0.8:
                position = fold(meta.get("position", ""))
                if all(word in position or word in name for word in words):
                    best = max(best, 0.82)
            if best >= 0.8:
                scored.append(
                    (best, {**meta, "match": round(best, 3), "card": chunk.text})
                )

        if not scored:
            return []

        # Однофамильцы: «Котельникова» — это и родительный падеж заведующего
        # кафедрой из академии, и точная фамилия преподавателя из общего списка
        # РУДН. Точное совпадение формально выше, но киоск стоит в холле
        # академии, и спрашивают почти всегда про своих. Поэтому близкие по
        # оценке варианты считаем равными и внутри них ставим академию первой.
        best = max(item[0] for item in scored)
        scored.sort(
            key=lambda item: (
                item[0] < best - SCOPE_BAND,
                item[1].get("scope") != "academy",
                -item[0],
            )
        )
        return [item[1] for item in scored[:limit]]

    def latest_news(
        self, limit: int = 5, tag: str | None = None
    ) -> list[dict[str, Any]]:
        items = [c for c in self.chunks if c.kind == "news" and c.id.endswith("#0")]
        if tag:
            needle = fold(tag)
            items = [
                c
                for c in items
                if needle in fold(c.title)
                or any(needle in fold(t) for t in (c.meta or {}).get("tags", []))
            ]
        items.sort(key=lambda c: _parse_date(c.date), reverse=True)
        return [
            {"title": c.title, "date": c.date, "url": c.url, "text": c.text[:600]}
            for c in items[:limit]
        ]

    def by_kind(self, kind: str) -> list[Chunk]:
        return [c for c in self.chunks if c.kind == kind]

    def stats(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.kind] = counts.get(chunk.kind, 0) + 1
        return {
            "chunks": len(self.chunks),
            "by_kind": counts,
            "dense": self.dense is not None,
            **self.meta,
        }
