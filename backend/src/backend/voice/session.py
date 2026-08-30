"""Состояние одного голосового соединения.

Поток из браузера всё время идёт в Vosk. Как только тот слышит «Рудик»,
начинаем копить звук (вместе с предысторией, чтобы не потерять начало фразы),
а по паузе отдаём фрагмент в GigaAM и дальше агенту.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import numpy as np

from backend.agent.graph import (
    AgentUnavailable,
    ThinkFilter,
    extract_sources,
    stream_answer,
    strip_sources,
)
from backend.config import Settings, get_settings
from backend.voice import asr, tts
from backend.voice.hotword import HotwordStream, heard_wake_word
from backend.voice.wakeword import detect_anywhere

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2

# Порог громкости, ниже которого кадр считается тишиной. Абсолютный нижний
# нужен для совсем тихого зала, множитель к фоновому шуму — для шумного холла.
SILENCE_FLOOR = 250.0
SILENCE_FACTOR = 2.0
# Реплику короче этого не закрываем: иначе пауза после обращения сойдёт
# за конец фразы, и вопрос обрежется.
MIN_SPEECH_MS = 300.0


def frame_rms(frame: bytes) -> float:
    """Громкость кадра. По ней ловим конец реплики, не дожидаясь Vosk."""
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


# Первую фразу отдаём на озвучку совсем короткой — ради быстрого старта речи:
# синтез «Привет!» занимает полсекунды против трёх на полный абзац. Следующие
# берём длиннее, иначе синтез рвёт интонацию на куски.
FIRST_PHRASE_CHARS = 6
NEXT_PHRASE_CHARS = 70
_SENTENCE_END = re.compile(r"[.!?…][\"'»)]*\s")


def split_phrase(text: str, *, first: bool) -> tuple[str, str]:
    """Отрезает от накопленного текста законченную фразу для озвучки.

    Возвращает саму фразу и остаток. Пустая фраза значит «ещё рано»:
    предложение не закончилось или вышло слишком коротким.
    """
    limit = FIRST_PHRASE_CHARS if first else NEXT_PHRASE_CHARS
    # Режем по последней границе, а не по первой: иначе короткие предложения
    # по отдельности никогда не дотянут до порога и озвучка встанет.
    end = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
    if end >= limit:
        return text[:end], text[end:]
    return "", text


Emit = Callable[[dict[str, Any]], Awaitable[None]]


class StreamSession:
    """Машина состояний: ждём обращения -> пишем реплику -> отвечаем."""

    def __init__(
        self, emit: Emit, session_id: str, settings: Settings | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.emit = emit
        self.session_id = session_id or "kiosk"

        self.hotword = HotwordStream(self.settings)
        # Кольцевой буфер предыстории: в нём лежит звук до срабатывания.
        preroll_frames = max(1, int(self.settings.stream_preroll_ms / 64))
        self.preroll: deque[bytes] = deque(maxlen=preroll_frames)
        self.capture: list[bytes] = []

        self.mode = "waiting"
        self.started_at = 0.0
        # Ссылку держим при себе: без неё задачу прогрева может убрать сборщик.
        self._warmup: asyncio.Task[object] | None = None
        # Текущий ответ и его озвучка: обе задачи обрывают при перехвате.
        self.answering: asyncio.Task[None] | None = None
        self.speaker: asyncio.Task[None] | None = None
        self.last_partial = ""
        # Оценка фонового шума копится, пока зал молчит, и задаёт порог тишины.
        self.noise = SILENCE_FLOOR
        self.silence_ms = 0.0
        self.voiced_ms = 0.0
        # Текст сегментов, которые Vosk уже закрыл внутри одной реплики.
        self.said = ""
        self.ended = False

    @property
    def ready(self) -> bool:
        return self.hotword.ready

    async def start(self) -> None:
        # Голос грузится и раскачивается несколько секунд — забираем их, пока
        # в зале тишина, чтобы первый же ответ не ждал прогрева.
        if tts.available(self.settings):
            self._warmup = asyncio.create_task(
                asyncio.to_thread(tts.warmup, self.settings)
            )

        await self.emit(
            {
                "type": "ready",
                "hotword": self.hotword.ready,
                "asr": asr.available(),
                "wake_word": self.settings.wake_word,
            }
        )

    async def feed(self, pcm16: bytes) -> None:
        """Принимает очередной кадр 16 кГц PCM16 из браузера."""
        self.preroll.append(pcm16)
        if not self.hotword.ready:
            return

        loudness = frame_rms(pcm16)
        text, final = await asyncio.to_thread(self.hotword.accept, pcm16)

        if self.mode == "answering":
            # Рудик отвечает, но зал слышно: обращение поверх ответа обрывает
            # озвучку. Эхо собственных колонок гасит браузер, а своё имя Рудик
            # в ответах не произносит — иначе перебивал бы сам себя.
            if text and heard_wake_word(text):
                await self._interrupt()
            elif final:
                self.hotword.reset()
            return

        if self.mode == "waiting":
            # Пока ждём обращения, запоминаем, насколько шумно в холле.
            self.noise = 0.97 * self.noise + 0.03 * loudness
            if text and heard_wake_word(text):
                await self._begin_capture()
            elif final:
                # Реплика не про нас — забываем и слушаем дальше.
                self.hotword.reset()
            return

        # Идёт запись реплики.
        self.capture.append(pcm16)
        if text and text != self.last_partial:
            self.last_partial = text
            await self.emit({"type": "partial", "text": text})

        frame_ms = len(pcm16) / 2 / SAMPLE_RATE * 1000
        if loudness < max(SILENCE_FLOOR, self.noise * SILENCE_FACTOR):
            self.silence_ms += frame_ms
        else:
            self.silence_ms = 0.0
            self.voiced_ms += frame_ms

        # Vosk закрывает фразу примерно через треть секунды тишины, а люди
        # делают паузы длиннее, подбирая слово: «Рудик, где находится... кабинет
        # Салтыковой». Поэтому его вердикт не принимаем сразу, а ждём, что
        # тишина продержится. Заговорил снова — пишем дальше, склеив куски.
        if final:
            if text:
                self.said = f"{self.said} {text}".strip()
            self.ended = True
        elif loudness >= max(SILENCE_FLOOR, self.noise * SILENCE_FACTOR):
            self.ended = False

        spoke_enough = self.voiced_ms >= MIN_SPEECH_MS
        confirmed = (
            self.ended and self.silence_ms >= self.settings.stream_endpoint_hold_ms
        )
        # Предохранитель на случай, если Vosk почему-то не закрыл фразу вовсе.
        hushed = spoke_enough and self.silence_ms >= self.settings.stream_silence_ms

        captured_seconds = len(self.capture) * len(pcm16) / BYTES_PER_SECOND
        if (
            confirmed
            or hushed
            or captured_seconds >= self.settings.stream_max_utterance_s
        ):
            await self._finish_capture(f"{self.said} {text}".strip())

    async def _begin_capture(self) -> None:
        self.mode = "capturing"
        self.started_at = time.monotonic()
        # Предыстория содержит и само обращение — с ней фраза не обрезается.
        self.capture = list(self.preroll)
        self.silence_ms = 0.0
        self.voiced_ms = 0.0
        self.said = ""
        self.ended = False
        # Всё, что говорили в зале до обращения, Vosk держит в своём результате.
        # Сбрасываем его, чтобы на экран шёл только сам вопрос: точный текст
        # всё равно даст GigaAM по накопленному звуку.
        self.hotword.reset()
        self.last_partial = ""
        await self.emit({"type": "wake"})

    async def _finish_capture(self, rough_text: str) -> None:
        """Закрывает реплику и запускает ответ отдельной задачей.

        Именно отдельной: пока идёт ответ, `feed` должен продолжать принимать
        кадры, иначе перебить Рудика голосом будет нечем.
        """
        self.mode = "answering"
        audio = b"".join(self.capture)
        self.capture = []
        self.preroll.clear()
        self.hotword.reset()

        await self.emit({"type": "thinking", "text": rough_text})
        self.answering = asyncio.create_task(self._run_answer(audio, rough_text))

    async def _run_answer(self, audio: bytes, rough_text: str) -> None:
        try:
            await self._answer(audio, rough_text)
        except asyncio.CancelledError:
            # Перебили — это нормальный ход событий, не ошибка.
            raise
        except AgentUnavailable as exc:
            # Ожидаемый простой сервера модели: в зал идёт вежливый текст,
            # а не код ошибки. Подробности уже записал сам агент.
            await self.emit({"type": "error", "message": str(exc)})
        except Exception as exc:
            log.exception("Ошибка обработки реплики")
            await self.emit({"type": "error", "message": str(exc)})
        finally:
            if self.mode == "answering":
                self.mode = "waiting"
                self.last_partial = ""
                await self.emit({"type": "listening"})

    async def _interrupt(self) -> None:
        """Посетитель заговорил поверх ответа: обрываем и слушаем его."""
        task, speaker = self.answering, self.speaker
        self.answering = self.speaker = None
        self.mode = "waiting"
        for running in (task, speaker):
            if running is not None and not running.done():
                running.cancel()
                with suppress(asyncio.CancelledError):
                    await running
        log.info("Ответ прерван обращением")
        await self.emit({"type": "interrupt"})
        await self._begin_capture()

    async def _answer(self, audio: bytes, rough_text: str) -> None:
        samples = asr.pcm16_to_float(audio)
        if samples.size < SAMPLE_RATE // 2:
            await self.emit({"type": "error", "message": "Реплика слишком короткая"})
            return

        # Точный текст даёт GigaAM; Vosk нужен был только чтобы поймать момент.
        try:
            text = await asyncio.to_thread(asr.transcribe_pcm, samples, self.settings)
        except RuntimeError as exc:
            await self.emit({"type": "error", "message": str(exc)})
            return

        wake = detect_anywhere(text or rough_text)
        question = (wake.command if wake.detected else text).strip()
        await self.emit({"type": "question", "text": question or text})

        if not question:
            await self.emit({"type": "error", "message": "Не разобрал вопрос"})
            return

        # Текст отдаём по мере генерации: первые слова появляются на экране
        # примерно через секунду, а не через паузу на весь ответ и озвучку.
        think = ThinkFilter()
        parts: list[str] = []
        # Озвучка идёт параллельно генерации, фраза за фразой: ждать синтеза
        # всего ответа — это ещё несколько секунд тишины.
        phrases: asyncio.Queue[str | None] = asyncio.Queue()
        speaking = tts.available(self.settings)
        speaker = asyncio.create_task(self._speak(phrases)) if speaking else None
        # Держим ссылку: при перехвате озвучку надо оборвать вместе с ответом,
        # иначе она договорит уже поверх нового вопроса.
        self.speaker = speaker
        pending = ""
        said_first = False

        async def show(piece: str) -> None:
            if not piece:
                return
            parts.append(piece)
            await self.emit({"type": "token", "text": piece})

        try:
            async for event in stream_answer(question, self.session_id):
                if event["type"] != "token":
                    continue
                piece = think.feed(event["text"])
                if not piece:
                    continue
                await show(piece)
                if not speaking:
                    continue
                pending += piece
                phrase, pending = split_phrase(pending, first=not said_first)
                if phrase:
                    said_first = True
                    await phrases.put(phrase)

            tail = think.flush()
            await show(tail)
            pending += tail
        except asyncio.CancelledError:
            if speaker is not None:
                speaker.cancel()
            raise
        finally:
            if speaker is not None and not speaker.cancelled():
                if pending.strip():
                    await phrases.put(pending)
                await phrases.put(None)

        full = "".join(parts).strip()
        if not full:
            if speaker is not None:
                await speaker
            await self.emit({"type": "error", "message": "Не удалось получить ответ"})
            return

        spoken = strip_sources(full)
        await self.emit(
            {
                "type": "answer",
                "question": question,
                "answer": full,
                "spoken": spoken,
                "sources": extract_sources(full),
                # Придёт ли озвучка с сервера: если нет, браузер прочитает сам.
                "voice": bool(spoken and speaking),
            }
        )

        if speaker is not None:
            await speaker
            # Отдельное событие конца: по нему киоск понимает, что очередь
            # проигрывания больше не пополнится.
            await self.emit({"type": "audio_end"})

    async def _speak(self, phrases: asyncio.Queue[str | None]) -> None:
        """Озвучивает ответ по фразам, строго по очереди.

        Параллелить синтез нельзя: куски приедут вперемешку, и ответ
        прозвучит задом наперёд.
        """
        while True:
            phrase = await phrases.get()
            if phrase is None:
                return
            text = strip_sources(phrase).strip()
            if not text:
                continue
            try:
                audio = await tts.synthesize(text, self.settings)
            except Exception:
                log.exception("Не удалось озвучить фразу — остаётся текст на экране")
                continue
            if audio:
                await self.emit(
                    {
                        "type": "audio",
                        "audio": base64.b64encode(audio).decode("ascii"),
                        "audio_format": tts.media_type(self.settings),
                    }
                )

    def close(self) -> None:
        for task in (self._warmup, self.answering, self.speaker):
            if task is not None and not task.done():
                task.cancel()
        self.capture = []
        self.preroll.clear()


def resample_to_16k(samples: np.ndarray, source_rate: int) -> np.ndarray:
    """Простое линейное приведение частоты — на случай, если браузер прислал своё."""
    if source_rate == SAMPLE_RATE or samples.size == 0:
        return samples
    ratio = SAMPLE_RATE / source_rate
    target_length = int(round(samples.size * ratio))
    positions = np.linspace(0, samples.size - 1, target_length, dtype=np.float32)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)
