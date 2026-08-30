"""Синтез речи. По умолчанию — Silero: считает локально и звучит живее прочих.

Silero и Piper выдают фразу за доли секунды прямо на процессоре, тогда как
edge-tts ходит в облако Microsoft и время ответа там непредсказуемо — от
полусекунды до двадцати. Для киоска в холле предсказуемость важнее, поэтому
облачный движок оставлен запасным (`RUDIK_TTS_BACKEND=edge`), а Piper —
вариантом полегче, без torch (`RUDIK_TTS_BACKEND=piper`).

Если нужных пакетов нет, эндпоинт вернёт 503, а фронтенд озвучит ответ
встроенным в браузер SpeechSynthesis.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import wave

from backend.config import Settings, get_settings
from backend.voice.speechtext import clean_for_speech

log = logging.getLogger(__name__)

__all__ = [
    "available",
    "clean_for_speech",
    "media_type",
    "status",
    "synthesize",
    "voices",
    "warmup",
]

# Голоса Silero v4 для русского.
SILERO_VOICES = ("aidar", "eugene", "baya", "kseniya", "xenia")
SILERO_FEMALE = frozenset({"baya", "kseniya", "xenia"})

# Голоса Piper из каталога rhasspy/piper-voices.
PIPER_VOICES = (
    "ru_RU-dmitri-medium",
    "ru_RU-denis-medium",
    "ru_RU-irina-medium",
    "ru_RU-ruslan-medium",
)

_lock = threading.Lock()
_model = None
_model_key = ""
_load_error: str | None = None


def _installed(module: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def available(settings: Settings | None = None) -> bool:
    backend = (settings or get_settings()).tts_backend
    if backend == "silero":
        return _installed("torch")
    if backend == "piper":
        return _installed("piper")
    if backend == "edge":
        return _installed("edge_tts")
    return False


def media_type(settings: Settings | None = None) -> str:
    """Формат озвучки: локальные движки отдают WAV, edge — mp3."""
    return (
        "audio/mpeg"
        if (settings or get_settings()).tts_backend == "edge"
        else "audio/wav"
    )


def _current_voice(settings: Settings) -> str:
    if settings.tts_backend == "silero":
        return settings.silero_voice
    if settings.tts_backend == "piper":
        return settings.piper_voice
    return settings.tts_voice


def model_path(settings: Settings | None = None):
    """Файл модели для локальных движков."""
    settings = settings or get_settings()
    if settings.tts_backend == "silero":
        return (
            settings.models_dir
            / "silero"
            / settings.silero_model_url.rsplit("/", 1)[-1]
        )
    return settings.models_dir / "piper" / f"{settings.piper_voice}.onnx"


def download_model(settings: Settings | None = None):
    """Скачивает модель синтеза, если её ещё нет на диске."""
    settings = settings or get_settings()
    target = model_path(settings)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    if settings.tts_backend == "silero":
        import torch

        log.info("Скачиваю модель голоса Silero...")
        torch.hub.download_url_to_file(
            settings.silero_model_url, str(target), progress=False
        )
    else:
        from piper.download_voices import download_voice

        log.info("Скачиваю голос %s...", settings.piper_voice)
        download_voice(settings.piper_voice, target.parent)
    log.info("Модель синтеза сохранена в %s", target)
    return target


def _load(settings: Settings):
    """Загружает модель выбранного движка. Блокирующая — только из потока."""
    path = download_model(settings)
    if settings.tts_backend == "silero":
        import torch

        # Модель Silero упакована как torch package, а не как обычный чекпойнт.
        model = torch.package.PackageImporter(str(path)).load_pickle(
            "tts_models", "model"
        )
        model.to(torch.device("cuda" if settings.silero_cuda else "cpu"))
        return model

    from piper import PiperVoice

    return PiperVoice.load(path, use_cuda=settings.piper_cuda)


def get_model(settings: Settings | None = None):
    """Ленивая загрузка: модель весит десятки мегабайт и грузится секунду-полторы."""
    global _model, _model_key, _load_error
    settings = settings or get_settings()
    key = f"{settings.tts_backend}:{_current_voice(settings)}"
    if _model is not None and _model_key == key:
        return _model
    if _load_error is not None and _model_key == key:
        return None

    with _lock:
        if _model is None or _model_key != key:
            try:
                _model = _load(settings)
                _model_key = key
                _load_error = None
                log.info("Синтез речи готов: %s", key)
            except ImportError:
                _model_key = key
                _load_error = f"Зависимости синтеза не установлены ({settings.tts_backend}): uv sync --extra voice"
                log.warning(_load_error)
            except Exception as exc:
                _model_key = key
                _load_error = f"Не удалось загрузить голос: {exc}"
                log.exception(_load_error)
    return _model


# Чем греть синтез. Одной фразы мало: torch раскачивает свои графы под каждый
# новый вид входа, и первая реплика с восклицанием или числом снова стоила бы
# двух секунд. Прогоняем набор, покрывающий типичные концовки предложений.
WARMUP_PHRASES = ("Здравствуйте.", "Привет!", "Кабинет 204 на втором этаже.")


def warmup(settings: Settings | None = None) -> None:
    """Греет синтез: грузит модель и прогоняет через неё несколько фраз."""
    settings = settings or get_settings()
    if get_model(settings) is None:
        return
    for phrase in WARMUP_PHRASES:
        try:
            _synthesize_local(clean_for_speech(phrase), settings)
        except Exception:
            log.exception("Прогрев синтеза не удался — первый ответ будет медленнее")
            return


def _to_wav(samples, sample_rate: int) -> bytes:
    """Заворачивает моно float32 в WAV: браузер тензоры играть не умеет."""
    import numpy as np

    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return buffer.getvalue()


def _synthesize_local(speech: str, settings: Settings) -> bytes:
    """Блокирующий синтез — вызывать только из отдельного потока."""
    model = get_model(settings)
    if model is None:
        raise RuntimeError(_load_error or "Голос недоступен")

    if settings.tts_backend == "silero":
        audio = model.apply_tts(
            text=speech,
            speaker=settings.silero_voice,
            sample_rate=settings.silero_sample_rate,
            # Silero сам ставит ударения и ё — без них речь звучит механически.
            put_accent=True,
            put_yo=True,
        )
        return _to_wav(audio.numpy(), settings.silero_sample_rate)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        model.synthesize_wav(speech, handle)
    return buffer.getvalue()


async def _synthesize_edge(speech: str, settings: Settings, voice: str | None) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(
        speech, voice or settings.tts_voice, rate=settings.tts_rate
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


async def synthesize(
    text: str, settings: Settings | None = None, voice: str | None = None
) -> bytes:
    """Возвращает озвученный ответ: WAV от локальных движков, mp3 от edge."""
    settings = settings or get_settings()
    speech = clean_for_speech(text)
    if not speech:
        return b""

    backend = settings.tts_backend
    if backend in ("silero", "piper"):
        if not available(settings):
            raise RuntimeError(
                f"Зависимости синтеза не установлены ({backend}): uv sync --extra voice"
            )
        # Синтез считает модель и держит поток занятым — уводим его из цикла.
        return await asyncio.to_thread(_synthesize_local, speech, settings)

    if backend == "edge":
        if not available(settings):
            raise RuntimeError("edge-tts не установлен: uv sync --extra voice")
        return await _synthesize_edge(speech, settings, voice)

    raise RuntimeError(f"Синтез отключён или неизвестный бэкенд: {backend}")


async def voices(
    prefix: str = "ru-RU", settings: Settings | None = None
) -> list[dict[str, str]]:
    settings = settings or get_settings()
    if settings.tts_backend == "silero":
        return [
            {
                "name": name,
                "gender": "Female" if name in SILERO_FEMALE else "Male",
                "locale": "ru_RU",
            }
            for name in SILERO_VOICES
        ]
    if settings.tts_backend == "piper":
        return [
            {
                "name": name,
                "gender": "Female" if "irina" in name else "Male",
                "locale": "ru_RU",
            }
            for name in PIPER_VOICES
        ]

    if not _installed("edge_tts"):
        return []
    import edge_tts

    found = await edge_tts.list_voices()
    return [
        {"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
        for v in found
        if v["ShortName"].startswith(prefix)
    ]


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    local = settings.tts_backend in ("silero", "piper")
    return {
        "available": available(settings) and settings.tts_backend != "none",
        "backend": settings.tts_backend,
        "voice": _current_voice(settings),
        "downloaded": model_path(settings).exists() if local else True,
        "loaded": _model is not None if local else True,
        "error": _load_error if local else None,
    }
