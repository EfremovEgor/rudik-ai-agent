"""Сборка FastAPI-приложения Рудика."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import chat, knowledge, stream, voice
from backend.config import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Индекс поднимаем на старте, чтобы первый вопрос не ждал загрузку.
    from backend.rag.store import get_kb

    stats = get_kb(settings).stats()
    log.info(
        "База знаний: %s фрагментов, векторы: %s",
        stats.get("chunks"),
        stats.get("dense"),
    )

    from backend.agent.graph import check_llm

    llm = await check_llm(settings)
    if llm["reachable"]:
        log.info("Модель %s на %s", settings.model, settings.llm_base_url)
    else:
        log.warning(
            "Сервер модели %s недоступен: %s", settings.llm_base_url, llm["error"]
        )

    # Модели голоса греем в фоне: иначе первый вопрос ждёт их загрузку.
    warmup = asyncio.create_task(_warm_voice_models())
    try:
        yield
    finally:
        warmup.cancel()


async def _warm_voice_models() -> None:
    from backend.voice import asr, hotword

    try:
        await asyncio.to_thread(hotword.get_model)
        await asyncio.to_thread(asr.get_model)
        log.info("Модели голоса прогреты")
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Не удалось прогреть модели голоса")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Рудик — ассистент РУДН",
        version="0.1.0",
        lifespan=lifespan,
    )
    # allow_origins=["*"] несовместим с allow_credentials: браузер отклонит ответ.
    wildcard = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=not wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(knowledge.router)
    app.include_router(chat.router)
    app.include_router(voice.router)
    app.include_router(stream.router)
    return app


app = create_app()
