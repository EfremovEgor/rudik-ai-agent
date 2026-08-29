"""Запуск сервера: uv run rudik-serve (или uv run fastapi dev src/backend/app.py)."""

from __future__ import annotations

import logging

import uvicorn

from backend.config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    uvicorn.run(
        "backend.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
