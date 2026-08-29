"""Состояние базы знаний, прямой поиск и пересборка индекса."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from backend.agent.graph import check_llm
from backend.api.schemas import HealthResponse, SearchResponse
from backend.config import get_settings
from backend.rag.store import get_kb
from backend.voice import stt, tts

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["knowledge"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        wake_word=settings.wake_word,
        llm=await check_llm(settings),
        knowledge_base=get_kb().stats(),
        stt=stt.status(),
        tts=tts.status(),
    )


@router.get("/kb/search", response_model=SearchResponse)
async def search(
    q: str = Query(min_length=2),
    k: int = Query(default=6, ge=1, le=20),
    kind: str | None = None,
) -> SearchResponse:
    kb = get_kb()
    kinds = [kind] if kind and kind != "any" else None
    hits = kb.search(q, k=k, kinds=kinds)
    return SearchResponse(query=q, results=[hit.to_dict() for hit in hits])


@router.get("/kb/people")
async def people(q: str = Query(min_length=2), limit: int = Query(default=5, ge=1, le=20)) -> dict:
    return {"query": q, "people": get_kb().find_people(q, limit=limit)}


@router.get("/kb/news")
async def news(limit: int = Query(default=5, ge=1, le=20), tag: str | None = None) -> dict:
    return {"news": get_kb().latest_news(limit=limit, tag=tag)}


def _reindex_job(scrape: bool) -> None:
    from backend.rag.build import build_index
    from backend.scraper.pipeline import run_scrape, save

    settings = get_settings()
    if scrape:
        log.info("Запускаю обход сайта...")
        save(run_scrape(settings), settings)
    log.info("Пересобираю индекс...")
    build_index(settings)
    log.info("Готово")


@router.post("/kb/reindex")
async def reindex(background: BackgroundTasks, scrape: bool = False) -> dict[str, str]:
    """Пересобирает индекс в фоне. scrape=true — сначала заново обойти сайт."""
    if not get_settings().documents_path.exists() and not scrape:
        raise HTTPException(
            status_code=400, detail="Документов нет. Запустите с параметром scrape=true"
        )
    background.add_task(_reindex_job, scrape)
    return {"status": "started", "scrape": str(scrape)}
