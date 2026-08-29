"""Голосовой канал: распознавание, синтез и полный цикл «услышал — ответил».

Фронтенд шлёт сюда короткие фрагменты речи. Если в реплике нет обращения
«Рудик», ассистент молчит — так работает режим постоянного прослушивания.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.agent.graph import answer, strip_sources
from backend.api.schemas import TranscriptResponse, TtsRequest, VoiceAnswer, WakeInfo
from backend.config import get_settings
from backend.voice import stt, tts
from backend.voice.wakeword import detect

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


async def _read_audio(audio: UploadFile) -> bytes:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой аудиофайл")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Слишком длинная запись")
    return data


def _transcribe(data: bytes) -> stt.Transcript:
    try:
        return stt.transcribe(data)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Ошибка распознавания речи")
        raise HTTPException(status_code=500, detail=f"Ошибка распознавания: {exc}") from exc


@router.post("/stt", response_model=TranscriptResponse)
async def speech_to_text(audio: UploadFile = File(...)) -> TranscriptResponse:
    """Только расшифровка — без обращения к модели."""
    result = _transcribe(await _read_audio(audio))
    wake = detect(result.text)
    return TranscriptResponse(
        text=result.text,
        duration=result.duration,
        wake=WakeInfo(
            detected=wake.detected, command=wake.command, matched=wake.matched, score=wake.score
        ),
    )


@router.post("/tts")
async def text_to_speech(request: TtsRequest) -> Response:
    """Озвучивает текст и отдаёт mp3."""
    try:
        audio = await tts.synthesize(request.text, voice=request.voice)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not audio:
        raise HTTPException(status_code=400, detail="Нечего озвучивать")
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/ask", response_model=VoiceAnswer)
async def voice_ask(
    audio: UploadFile = File(...),
    session_id: str = Form("default"),
    require_wake_word: bool = Form(True),
    speak: bool = Form(True),
) -> VoiceAnswer:
    """Полный голосовой цикл: речь -> текст -> ответ агента -> речь."""
    settings = get_settings()
    data = await _read_audio(audio)
    transcript = _transcribe(data)
    wake = detect(transcript.text)
    info = WakeInfo(
        detected=wake.detected, command=wake.command, matched=wake.matched, score=wake.score
    )

    # Тишина или фраза не для нас — просто молчим.
    if require_wake_word and not wake.detected:
        return VoiceAnswer(question=transcript.text, wake=info, session_id=session_id)

    question = (wake.command if wake.detected else transcript.text).strip()
    if not question:
        question = "Расскажи, что ты умеешь."

    try:
        result = await answer(question, session_id)
    except Exception as exc:
        log.exception("Ошибка генерации ответа")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    spoken = strip_sources(result["text"])
    encoded = None
    if speak and tts.available() and spoken:
        try:
            audio_bytes = await tts.synthesize(spoken)
            encoded = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None
        except Exception:
            log.exception("Не удалось озвучить ответ — вернём только текст")

    return VoiceAnswer(
        question=question,
        answer=result["text"],
        spoken=spoken,
        sources=result["sources"],
        wake=info,
        audio=encoded,
        session_id=session_id,
    )


@router.get("/voices")
async def list_voices() -> dict[str, object]:
    return {"voices": await tts.voices(), "current": get_settings().tts_voice}
