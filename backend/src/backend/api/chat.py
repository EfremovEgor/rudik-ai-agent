"""Текстовый чат с Рудиком: потоковый (SSE) и обычный ответ."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.agent.graph import answer, extract_sources, stream_answer
from backend.api.schemas import ChatRequest, ChatResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Поток событий: token — кусочек ответа, tool — вызов инструмента, done — конец."""
    async def generate() -> AsyncIterator[str]:
        collected: list[str] = []
        try:
            async for event in stream_answer(request.message, request.session_id):
                if event["type"] == "token":
                    collected.append(event["text"])
                yield _sse(event)
        except Exception as exc:
            log.exception("Ошибка генерации ответа")
            yield _sse({"type": "error", "message": str(exc)})
        else:
            text = "".join(collected)
            yield _sse({"type": "done", "text": text, "sources": extract_sources(text)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sync", response_model=ChatResponse)
async def chat_sync(request: ChatRequest) -> ChatResponse:
    """Ответ целиком — удобно для интеграций и тестов."""
    try:
        result = await answer(request.message, request.session_id)
    except Exception as exc:
        log.exception("Ошибка генерации ответа")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        text=result["text"], sources=result["sources"], session_id=request.session_id
    )
