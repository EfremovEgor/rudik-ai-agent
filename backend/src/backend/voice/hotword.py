"""Постоянное прослушивание потока маленькой моделью Vosk.

Тяжёлую GigaAM нельзя гонять на весь поток — это и дорого, и медленно.
Поэтому поток всё время слушает Vosk (около 45 МБ, работает в реальном
времени), ищет обращение «Рудик» и отмечает конец реплики. GigaAM включается
только на выделенный фрагмент.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import zipfile
from pathlib import Path

from backend.config import Settings, get_settings
from backend.voice.wakeword import detect

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"

_lock = threading.Lock()
_model = None
_load_error: str | None = None


def available() -> bool:
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False
    return True


def model_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.models_dir / settings.hotword_model


def download_model(settings: Settings | None = None) -> Path:
    """Скачивает и распаковывает модель Vosk, если её ещё нет на диске."""
    settings = settings or get_settings()
    target = model_dir(settings)
    if (target / "am").exists() or (target / "conf").exists():
        return target

    import httpx

    url = MODEL_URL.format(name=settings.hotword_model)
    archive = settings.models_dir / f"{settings.hotword_model}.zip"
    settings.models_dir.mkdir(parents=True, exist_ok=True)

    log.info("Скачиваю модель обращения %s...", settings.hotword_model)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with archive.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 16):
                handle.write(chunk)

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(settings.models_dir)
    archive.unlink(missing_ok=True)

    # В архиве каталог называется так же, как модель, но подстрахуемся.
    if not target.exists():
        candidates = [p for p in settings.models_dir.iterdir() if p.is_dir() and "vosk" in p.name]
        if candidates:
            shutil.move(str(candidates[0]), str(target))
    log.info("Модель обращения распакована в %s", target)
    return target


def get_model(settings: Settings | None = None):
    global _model, _load_error
    if _model is not None:
        return _model
    if _load_error is not None:
        return None

    with _lock:
        if _model is None and _load_error is None:
            settings = settings or get_settings()
            try:
                import vosk

                vosk.SetLogLevel(-1)
                path = download_model(settings)
                _model = vosk.Model(str(path))
                log.info("Детектор обращения готов: %s", settings.hotword_model)
            except ImportError:
                _load_error = "vosk не установлен: uv sync --extra voice"
                log.warning(_load_error)
            except Exception as exc:
                _load_error = f"Не удалось загрузить модель обращения: {exc}"
                log.exception(_load_error)
    return _model


class HotwordStream:
    """Инкрементальный распознаватель одного соединения.

    Отдаёт две вещи: услышал ли обращение и закончилась ли реплика.
    Точность здесь не важна — за текст отвечает GigaAM.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._recognizer = None
        model = get_model(self.settings)
        if model is not None:
            import vosk

            self._recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            self._recognizer.SetWords(False)

    @property
    def ready(self) -> bool:
        return self._recognizer is not None

    def reset(self) -> None:
        if self._recognizer is not None:
            self._recognizer.Reset()

    def accept(self, pcm16: bytes) -> tuple[str, bool]:
        """Скармливает кадр и возвращает текущий текст и признак конца фразы.

        `final=True` означает, что Vosk услышал паузу и закрыл реплику.
        """
        if self._recognizer is None:
            return "", False
        if self._recognizer.AcceptWaveform(pcm16):
            result = json.loads(self._recognizer.Result())
            return (result.get("text") or "").strip(), True
        partial = json.loads(self._recognizer.PartialResult())
        return (partial.get("partial") or "").strip(), False

    def flush(self) -> str:
        if self._recognizer is None:
            return ""
        result = json.loads(self._recognizer.FinalResult())
        return (result.get("text") or "").strip()


def heard_wake_word(text: str) -> bool:
    """Обращение ищем тем же нечётким сопоставлением, что и в полном тексте."""
    return detect(text, window=6).detected


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    return {
        "available": available(),
        "model": settings.hotword_model,
        "loaded": _model is not None,
        "downloaded": model_dir(settings).exists(),
        "error": _load_error,
    }
