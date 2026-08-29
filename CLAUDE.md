# Рудик — заметки для работы в этом репозитории

Голосовой ассистент Инженерной академии РУДН. Два независимых приложения:
`backend/` (Python, uv) и `frontend/` (React, TanStack Start).

## Команды

```bash
# бэкенд (из backend/)
uv sync --extra rag --extra voice   # rag = fastembed, voice = whisper + edge-tts
uv run rudik-serve                  # API на 127.0.0.1:8000
uv run rudik-scrape --cache --index # пересобрать данные из кэша HTML
uv run rudik-index                  # только индекс

# фронтенд (из frontend/)
npm run dev      # 3000, /api проксируется на 8000
npm run lint
npm run build
```

## Что где лежит

| Путь | Ответственность |
|---|---|
| `backend/src/backend/scraper/` | обход сайта: `crawl` (BFS), `parsers` (типы страниц), `pipeline` (сборка документов) |
| `backend/src/backend/rag/` | `documents` (нарезка), `index` (BM25 + векторы + RRF), `store` (синглтон), `build` (CLI) |
| `backend/src/backend/agent/` | `tools` (инструменты), `graph` (LangGraph), `prompts` |
| `backend/src/backend/voice/` | `stt` (faster-whisper), `tts` (edge-tts), `wakeword` (нечёткий поиск «Рудик») |
| `backend/src/backend/api/` | роутеры FastAPI |
| `frontend/src/lib/` | `api.ts` (клиент), `rudik-store.ts` (TanStack Store) |
| `frontend/src/hooks/useVoiceSession.ts` | микрофон, VAD, отправка фрагментов речи |
| `frontend/src/components/rudik/` | аватар, голосовые контролы, чат, статус |

## Правила, о которых легко забыть

- **Модель Claude 5 не принимает `temperature`** — в `ChatAnthropic` его не
  передаём. Глубина рассуждений задаётся `reasoning_effort` (в `.env` —
  `RUDIK_EFFORT`, для голоса держим `low`).
- **User-Agent должен быть ASCII** — httpx кодирует заголовки в latin-1.
- **Ссылки со страницы собираются до `html.clean()`** — чистка выкидывает
  шапку с навигацией.
- **`<header>` внутри карточки сотрудника (`.uk-comment-header`) удалять
  нельзя** — там имя. Чистится только шапка сайта.
- **Тексты и комментарии в коде — на русском**, как и весь интерфейс.
- **Голосовые зависимости опциональны**: код должен деградировать до текста
  и браузерного синтеза, а не падать.

## Данные

`backend/data/` не коммитится. Если индекс пуст, `/api/health` покажет
`chunks: 0`, а поиск вернёт пустоту — нужно запустить скрапер.
