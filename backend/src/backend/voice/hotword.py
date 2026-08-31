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
from backend.voice.wakeword import detect_anywhere

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
        candidates = [
            p for p in settings.models_dir.iterdir() if p.is_dir() and "vosk" in p.name
        ]
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
    """Инкрементальные распознаватели одного соединения.

    Их два, и это принципиально. Пока ждём обращения, поток идёт в
    распознаватель с ограниченной грамматикой: ему разрешено услышать только
    имя ассистента, поэтому в шуме он не уходит в похожие слова. Когда реплику
    уже пишут, нужен обычный полный распознаватель — он даёт черновой текст на
    экран и отмечает конец фразы. Точность там не важна: за текст отвечает
    GigaAM.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._recognizer = None
        self._wake = None
        model = get_model(self.settings)
        if model is None:
            return

        import vosk

        self._recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
        self._recognizer.SetWords(False)

        if self.settings.hotword_grammar:
            # Слова вне словаря модели Vosk молча игнорирует, оставляя [unk].
            grammar = json.dumps(
                [self.settings.wake_word, "[unk]"], ensure_ascii=False
            )
            try:
                self._wake = vosk.KaldiRecognizer(model, SAMPLE_RATE, grammar)
                # Уверенность по словам: она отделяет настоящее обращение
                # от случайного, на которое декодер вынужден сводить всё
                # подряд, раз других слов ему не разрешено.
                self._wake.SetWords(True)
            except Exception:
                log.exception("Грамматика обращения не собралась — слушаем как обычно")

    @property
    def ready(self) -> bool:
        return self._recognizer is not None

    def reset(self) -> None:
        if self._recognizer is not None:
            self._recognizer.Reset()
        if self._wake is not None:
            self._wake.Reset()

    def accept_wake(self, pcm16: bytes, *, fast: bool = True) -> bool:
        """Слушает поток в ожидании обращения.

        Отдельный распознаватель с коротким словарём: в шумном холле обычный
        слышит вместо «Рудик» то «пороге», то «рубят», и киоск молчит. Обратная
        сторона — словаря почти нет, и чужую речь декодер тоже сводит к имени.

        Отсюда два режима. `fast` — для ожидания: срабатываем по частичному
        результату, ловим всё, а лишнее потом отсеет GigaAM по точному тексту.
        Строгий режим — для перехвата ответа: там ложное срабатывание рвёт
        ответ на полуслове, поэтому ждём закрытый сегмент с уверенностью.
        """
        if self._wake is None:
            text, final = self.accept(pcm16)
            if final:
                self.reset()
            return bool(text) and heard_wake_word(text)

        wake = self.settings.wake_word

        # Закрытый сегмент несёт уверенность — по ней отсеиваем случайные
        # совпадения, на которые декодер вынужден сводить всё подряд.
        if self._wake.AcceptWaveform(pcm16):
            result = json.loads(self._wake.Result())
            self._wake.Reset()
            return any(
                word.get("word") == wake
                and float(word.get("conf", 0.0)) >= self.settings.hotword_confidence
                for word in result.get("result", [])
            )

        if not fast:
            return False

        # Частичный результат уверенности не содержит, зато появляется сразу.
        # Ждать закрытия сегмента нельзя: человек говорит без пауз, и сегмент
        # закроется только в конце фразы — обращение к тому времени устареет.
        partial = (json.loads(self._wake.PartialResult()).get("partial") or "").split()
        return wake in partial

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
    """Обращение ищем тем же нечётким сопоставлением, что и в полном тексте.

    Без окна в начале: сюда приходит накопленный частичный результат Vosk,
    и «Рудик» может стоять хоть двадцатым словом.
    """
    return detect_anywhere(text).detected


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    return {
        "available": available(),
        "model": settings.hotword_model,
        "loaded": _model is not None,
        "downloaded": model_dir(settings).exists(),
        "error": _load_error,
    }
