"""Синтез речи. По умолчанию — edge-tts: русские голоса хорошего качества и без ключа.

Если пакет не установлен, эндпоинт вернёт 503, а фронтенд озвучит ответ
встроенным в браузер SpeechSynthesis.
"""

from __future__ import annotations

import logging
import re

from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

# Ссылки и служебные символы не озвучиваем.
_URL = re.compile(r"https?://\S+")
_MARKUP = re.compile(r"[*_`#>|]+")
_SPACES = re.compile(r"\s+")


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def clean_for_speech(text: str) -> str:
    text = _URL.sub("", text)
    text = text.replace("//", " ")
    text = _MARKUP.sub(" ", text)
    text = text.replace("—", "-").replace("№", "номер ")
    return _SPACES.sub(" ", text).strip()


async def synthesize(text: str, settings: Settings | None = None, voice: str | None = None) -> bytes:
    """Возвращает mp3 с озвученным ответом."""
    settings = settings or get_settings()
    speech = clean_for_speech(text)
    if not speech:
        return b""

    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts не установлен: uv sync --extra voice") from exc

    communicate = edge_tts.Communicate(
        speech, voice or settings.tts_voice, rate=settings.tts_rate
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


async def voices(prefix: str = "ru-RU") -> list[dict[str, str]]:
    try:
        import edge_tts
    except ImportError:
        return []
    found = await edge_tts.list_voices()
    return [
        {"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
        for v in found
        if v["ShortName"].startswith(prefix)
    ]


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    return {
        "available": available() and settings.tts_backend != "none",
        "backend": settings.tts_backend,
        "voice": settings.tts_voice,
    }
