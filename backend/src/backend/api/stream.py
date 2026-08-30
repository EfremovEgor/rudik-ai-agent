"""Постоянный голосовой канал: браузер льёт звук, сервер решает, когда слушать.

Клиент шлёт бинарные кадры моно PCM16 с частотой 16 кГц, сервер отвечает
JSON-событиями: ready, wake, partial, thinking, question, token, answer, audio,
listening, error. Такой канал заметно быстрее загрузки файлов: обращение
ловится на лету, а тяжёлая модель включается только на саму реплику.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config import get_settings
from backend.voice.session import StreamSession

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])

# Кадр в 64 мс при 16 кГц — 2048 байт. Разумный потолок против мусора.
MAX_FRAME_BYTES = 64 * 1024


@router.websocket("/stream")
async def voice_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    session_id = websocket.query_params.get("session_id", "kiosk")

    async def emit(event: dict) -> None:
        await websocket.send_text(json.dumps(event, ensure_ascii=False))

    session = StreamSession(emit, session_id, settings)
    log.info("Голосовой канал открыт (%s)", session_id)

    try:
        await session.start()
        if not session.ready:
            await emit(
                {
                    "type": "error",
                    "message": "Детектор обращения не загрузился — смотрите /api/health",
                }
            )

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data:
                if len(data) <= MAX_FRAME_BYTES:
                    await session.feed(data)
                continue

            text = message.get("text")
            if text:
                # Пока из текстовых команд нужен только пинг для keepalive.
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "ping":
                    await emit({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Ошибка голосового канала")
    finally:
        session.close()
        log.info("Голосовой канал закрыт (%s)", session_id)
