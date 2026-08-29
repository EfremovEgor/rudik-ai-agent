"""Распознавание обращения «Рудик» в расшифрованной реплике."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from backend.textutil import fold

# Whisper и Web Speech API пишут имя по-разному — принимаем все близкие варианты.
ALIASES = (
    "рудик", "рудике", "рудику", "рудика", "рудиком", "руди",
    "рудек", "родик", "рудник", "рудич", "рудин", "будик", "худик", "рудный",
    "rudik", "roodik", "rudick",
)

# Обращение обычно отделено запятой или паузой.
_SPLIT = re.compile(r"^[\s,.!?:;—-]+")
_WORD = re.compile(r"[\w-]+", re.UNICODE)


@dataclass
class WakeResult:
    detected: bool
    command: str
    matched: str = ""
    score: float = 0.0


def score_token(token: str) -> tuple[float, str]:
    token = token.strip("«»\"'()[[]").strip()
    if not token:
        return 0.0, ""
    best, alias = 0.0, ""
    for candidate in ALIASES:
        ratio = difflib.SequenceMatcher(None, token, candidate).ratio()
        if ratio > best:
            best, alias = ratio, candidate
    if token.startswith("руди"):
        best = max(best, 0.95)
    return best, alias


def detect(text: str, *, threshold: float = 0.78, window: int = 5) -> WakeResult:
    """Ищет имя ассистента в начале реплики и возвращает остаток как команду.

    Имя ищется только в первых `window` словах: «Рудик, где кабинет?» — обращение,
    а «мне сказал Рудик» — уже нет. Окно с запасом, потому что распознавание
    любит добавить в начало «Так», «Ну» или «Эм».
    """
    normalized = fold(text)
    if not normalized:
        return WakeResult(False, "")

    tokens = _WORD.findall(normalized)
    for position, token in enumerate(tokens[:window]):
        score, alias = score_token(token)
        if score >= threshold:
            # Отрезаем всё до конца найденного слова в исходном тексте.
            match = re.search(re.escape(token), fold(text))
            tail = text[match.end():] if match else ""
            command = _SPLIT.sub("", tail).strip()
            return WakeResult(True, command, matched=alias, score=round(score, 3))

    return WakeResult(False, text.strip())
