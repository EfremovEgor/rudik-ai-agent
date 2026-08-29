"""Состояние одного голосового соединения.

Поток из браузера всё время идёт в Vosk. Как только тот слышит «Рудик»,
начинаем копить звук (вместе с предысторией, чтобы не потерять начало фразы),
а по паузе отдаём фрагмент в GigaAM и дальше агенту.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from backend.agent.graph import answer as agent_answer
from backend.agent.graph import strip_sources
from backend.config import Settings, get_settings
from backend.voice import asr, tts
from backend.voice.hotword import HotwordStream, heard_wake_word
from backend.voice.wakeword import detect

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2

Emit = Callable[[dict[str, Any]], Awaitable[None]]


class StreamSession:
    """Машина состояний: ждём обращения -> пишем реплику -> отвечаем."""

    def __init__(self, emit: Emit, session_id: str, settings: Settings | None = None) -> None:
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
        self.last_partial = ""
        self.silence_bytes = 0

    @property
    def ready(self) -> bool:
        return self.hotword.ready

    async def start(self) -> None:
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
        # Пока Рудик думает или говорит, входящий звук игнорируем,
        # иначе он услышит собственный ответ.
        if self.mode == "busy":
            return

        self.preroll.append(pcm16)
        if not self.hotword.ready:
            return

        text, final = await asyncio.to_thread(self.hotword.accept, pcm16)

        if self.mode == "waiting":
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

        captured_seconds = len(self.capture) * len(pcm16) / BYTES_PER_SECOND
        if final or captured_seconds >= self.settings.stream_max_utterance_s:
            await self._finish_capture(text)

    async def _begin_capture(self) -> None:
        self.mode = "capturing"
        self.started_at = time.monotonic()
        # Предыстория содержит и само обращение — с ней фраза не обрезается.
        self.capture = list(self.preroll)
        self.last_partial = ""
        await self.emit({"type": "wake"})

    async def _finish_capture(self, rough_text: str) -> None:
        self.mode = "busy"
        audio = b"".join(self.capture)
        self.capture = []
        self.preroll.clear()
        self.hotword.reset()

        await self.emit({"type": "thinking", "text": rough_text})
        try:
            await self._answer(audio, rough_text)
        except Exception as exc:
            log.exception("Ошибка обработки реплики")
            await self.emit({"type": "error", "message": str(exc)})
        finally:
            self.mode = "waiting"
            self.last_partial = ""
            await self.emit({"type": "listening"})

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

        wake = detect(text or rough_text, window=6)
        question = (wake.command if wake.detected else text).strip()
        await self.emit({"type": "question", "text": question or text})

        if not question:
            await self.emit({"type": "error", "message": "Не разобрал вопрос"})
            return

        result = await agent_answer(question, self.session_id)
        spoken = strip_sources(result["text"])

        encoded = None
        if spoken and tts.available():
            try:
                audio_bytes = await tts.synthesize(spoken, self.settings)
                encoded = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None
            except Exception:
                log.exception("Не удалось озвучить ответ — отдаём только текст")

        await self.emit(
            {
                "type": "answer",
                "question": question,
                "answer": result["text"],
                "spoken": spoken,
                "sources": result["sources"],
                "audio": encoded,
                "audio_format": "audio/mpeg",
            }
        )

    def close(self) -> None:
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
