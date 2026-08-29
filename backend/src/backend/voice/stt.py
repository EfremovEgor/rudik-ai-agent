"""Распознавание речи локальной моделью faster-whisper.

Модель поднимается лениво и живёт в процессе: первая загрузка занимает
несколько секунд, дальше распознавание фразы на CPU — доли секунды.
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache

from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_model = None
_load_error: str | None = None


@dataclass
class Transcript:
    text: str
    language: str = "ru"
    duration: float = 0.0


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def get_model(settings: Settings | None = None):
    """Возвращает загруженную модель или None, если faster-whisper не установлен."""
    global _model, _load_error
    if _model is not None:
        return _model
    if _load_error is not None:
        return None

    with _lock:
        if _model is None and _load_error is None:
            settings = settings or get_settings()
            try:
                from faster_whisper import WhisperModel

                log.info("Загружаю модель распознавания речи %s...", settings.stt_model)
                _model = WhisperModel(
                    settings.stt_model,
                    device=settings.stt_device,
                    compute_type=settings.stt_compute,
                )
            except ImportError:
                _load_error = "faster-whisper не установлен: uv sync --extra voice"
                log.warning(_load_error)
            except Exception as exc:  # модель могла не скачаться
                _load_error = f"Не удалось загрузить модель распознавания: {exc}"
                log.exception(_load_error)
    return _model


@lru_cache(maxsize=1)
def domain_prompt() -> str:
    """Словарь предметной области для Whisper.

    Модель сильнее ошибается именно на фамилиях и названиях кафедр, а
    initial_prompt смещает её в сторону перечисленных слов. Помещается около
    двух сотен токенов, поэтому берём то, о чём спрашивают чаще всего:
    дирекцию, заведующих кафедрами и названия кафедр.
    """
    base = "Рудик. Инженерная академия РУДН. Кафедра, кабинет, расписание, приёмная комиссия."
    try:
        from backend.rag.store import get_kb

        kb = get_kb()
    except Exception:  # база может быть ещё не собрана
        return base

    names: list[str] = []
    for chunk in kb.by_kind("person"):
        meta = chunk.meta or {}
        unit = meta.get("unit") or ""
        if "Дирекция" not in unit:
            continue
        surname = (meta.get("name") or chunk.title).split()
        if surname:
            names.append(surname[0])

    departments = []
    for chunk in kb.by_kind("department"):
        departments.append(chunk.title.replace("Кафедра ", ""))
        head = (chunk.meta or {}).get("head") or ""
        if head:
            names.append(head.split()[0])

    unique_names = list(dict.fromkeys(names))
    vocabulary = f"{base} {', '.join(unique_names[:30])}. {', '.join(departments[:10])}."
    return vocabulary[:900]


def transcribe(audio: bytes, settings: Settings | None = None) -> Transcript:
    """Распознаёт речь из аудиофайла (webm/ogg/wav/mp3 — декодирует PyAV)."""
    settings = settings or get_settings()
    model = get_model(settings)
    if model is None:
        raise RuntimeError(_load_error or "Распознавание речи недоступно")

    segments, info = model.transcribe(
        io.BytesIO(audio),
        language="ru",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
        # Подсказка со словарём академии: заметно снижает ошибки в фамилиях.
        initial_prompt=domain_prompt(),
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return Transcript(text=text, language=info.language or "ru", duration=info.duration or 0.0)


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    return {
        "available": available(),
        "model": settings.stt_model,
        "device": settings.stt_device,
        "loaded": _model is not None,
        "error": _load_error,
    }
