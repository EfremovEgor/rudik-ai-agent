"""Распознавание обращения «Рудик» в расшифрованной реплике."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from backend.textutil import fold

# Whisper и Web Speech API пишут имя по-разному — принимаем все близкие варианты.
# Короткие огрызки вроде «руди» сюда не кладём: на них ловятся посторонние
# слова («орудий»). Начало «руди» и так покрыто отдельным правилом ниже.
ALIASES = (
    "рудик",
    "рудике",
    "рудику",
    "рудика",
    "рудиком",
    "рудек",
    "родик",
    "рудник",
    "рудич",
    "рудин",
    "будик",
    "худик",
    "рудный",
    "rudik",
    "roodik",
    "rudick",
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
    # Слово, начинающееся на «руди», — почти наверняка обращение, но только
    # если это не длинное постороннее слово («рудиментарный»).
    if token.startswith("руди") and len(token) <= 8:
        best = max(best, 0.95)
    return best, alias


def _scan(
    text: str, threshold: float
) -> tuple[list[re.Match[str]], list[tuple[int, str, float]]]:
    """Разбирает текст на слова и возвращает все места, похожие на имя.

    Границы слов берём по исходному тексту, чтобы потом отрезать команду
    без сдвигов: `fold` схлопывает пробелы и индексы уезжают.
    """
    spans = list(_WORD.finditer(text))
    hits: list[tuple[int, str, float]] = []
    for position, span in enumerate(spans):
        score, alias = score_token(fold(span.group(0)))
        if score >= threshold:
            hits.append((position, alias, score))
    return spans, hits


def _tail(text: str, span: re.Match[str], alias: str, score: float) -> WakeResult:
    command = _SPLIT.sub("", text[span.end() :]).strip()
    return WakeResult(True, command, matched=alias, score=round(score, 3))


def detect(text: str, *, threshold: float = 0.78, window: int = 5) -> WakeResult:
    """Ищет имя ассистента в начале реплики и возвращает остаток как команду.

    Имя ищется только в первых `window` словах: «Рудик, где кабинет?» — обращение,
    а «мне сказал Рудик» — уже нет. Окно с запасом, потому что распознавание
    любит добавить в начало «Так», «Ну» или «Эм».
    """
    if not fold(text):
        return WakeResult(False, "")

    spans, hits = _scan(text, threshold)
    for position, alias, score in hits:
        if position < window:
            return _tail(text, spans[position], alias, score)
    return WakeResult(False, text.strip())


def detect_anywhere(text: str, *, threshold: float = 0.78) -> WakeResult:
    """То же, но без окна в начале и по последнему совпадению.

    Нужно для постоянного потока: Vosk копит частичный результат, пока в зале
    не наступит пауза, и обращение оказывается далеко не первым словом —
    окно `detect` его просто не видит. Берём последнее совпадение, потому что
    вопрос идёт после самого свежего «Рудик».
    """
    if not fold(text):
        return WakeResult(False, "")

    spans, hits = _scan(text, threshold)
    if not hits:
        return WakeResult(False, text.strip())
    position, alias, score = hits[-1]
    return _tail(text, spans[position], alias, score)
