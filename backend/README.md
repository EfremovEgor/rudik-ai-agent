# Рудик — бэкенд

FastAPI + LangGraph + Claude, локальное распознавание и синтез речи,
собственный скрапер academy.rudn.ru и гибридный поиск по собранным данным.

## Установка

```bash
cp .env.example .env        # вписать ANTHROPIC_API_KEY
uv sync --extra rag --extra voice
```

Экстры можно не ставить: без `rag` поиск работает на одном BM25,
без `voice` отключаются распознавание и синтез речи.

## Команды

```bash
uv run rudik-scrape --index   # обойти сайт и собрать индекс
uv run rudik-scrape --cache   # пересобрать из сохранённого HTML
uv run rudik-index            # только индекс
uv run rudik-serve            # запустить API
```

Полное описание проекта — в README в корне репозитория.
