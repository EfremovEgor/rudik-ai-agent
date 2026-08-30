"""Распознавание речи: GigaAM v3 (E2E RNN-T) в ONNX.

Модель заточена под русский и заметно точнее Whisper на именах и терминах.
Она тяжёлая, поэтому запускается не на весь поток, а только на реплику,
которую уже выделил детектор обращения (см. hotword.py).
"""

from __future__ import annotations

import io
import logging
import threading

import numpy as np

from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

_lock = threading.Lock()
_model = None
_load_error: str | None = None


def available() -> bool:
    try:
        import onnx_asr  # noqa: F401
    except ImportError:
        return False
    return True


def get_model(settings: Settings | None = None):
    """Лениво поднимает модель. Первый вызов скачивает веса с Hugging Face."""
    global _model, _load_error
    if _model is not None:
        return _model
    if _load_error is not None:
        return None

    with _lock:
        if _model is None and _load_error is None:
            settings = settings or get_settings()
            try:
                import onnx_asr

                log.info(
                    "Загружаю модель распознавания %s (%s)...",
                    settings.asr_model,
                    settings.asr_quantization or "fp32",
                )
                _model = onnx_asr.load_model(
                    settings.asr_model,
                    quantization=settings.asr_quantization or None,
                )
                log.info("Модель распознавания готова")
            except ImportError:
                _load_error = "onnx-asr не установлен: uv sync --extra voice"
                log.warning(_load_error)
            except Exception as exc:
                _load_error = f"Не удалось загрузить модель распознавания: {exc}"
                log.exception(_load_error)
    return _model


def transcribe_pcm(samples: np.ndarray, settings: Settings | None = None) -> str:
    """Распознаёт моно float32 в диапазоне [-1, 1] с частотой 16 кГц."""
    model = get_model(settings)
    if model is None:
        raise RuntimeError(_load_error or "Распознавание речи недоступно")
    if samples.size == 0:
        return ""

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    text = model.recognize(audio, sample_rate=SAMPLE_RATE)
    return (text or "").strip()


def decode_audio(data: bytes) -> np.ndarray:
    """Приводит webm/ogg/mp3/wav из браузера к моно float32 16 кГц."""
    try:
        import av
    except ImportError as exc:
        raise RuntimeError(
            "Для разбора аудиофайлов нужен av: uv sync --extra voice"
        ) from exc

    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(
            format="s16", layout="mono", rate=SAMPLE_RATE
        )
        chunks: list[np.ndarray] = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
        # Ресемплер придерживает хвост — дожимаем его пустым кадром.
        for resampled in resampler.resample(None):
            chunks.append(resampled.to_ndarray().reshape(-1))

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
    return pcm


def pcm16_to_float(data: bytes) -> np.ndarray:
    """Кадры из браузера приходят как 16-битный PCM."""
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    return {
        "available": available(),
        "model": settings.asr_model,
        "quantization": settings.asr_quantization or "fp32",
        "loaded": _model is not None,
        "error": _load_error,
    }
