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
uv run python scripts/bench_stt.py  # WER распознавания на типичных вопросах
uv run python scripts/check_stream.py  # прогон записи через голосовой канал

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
| `backend/src/backend/voice/` | `asr` (GigaAM в ONNX), `hotword` (Vosk на потоке), `session` (машина состояний канала), `tts`, `wakeword` (нечёткое сравнение) |
| `backend/src/backend/api/` | роутеры FastAPI |
| `frontend/src/lib/` | `api.ts` (клиент), `rudik-store.ts` (состояния экрана) |
| `frontend/src/hooks/useVoiceStream.ts` | микрофон, AudioWorklet, вебсокет с сервером |
| `frontend/public/rudik-capture.js` | AudioWorklet: кадры моно PCM16 16 кГц |
| `frontend/src/components/rudik/` | киоск: сцена с позами, шапка и подвал, панель состояния |

## Правила, о которых легко забыть

- **Модель self-hosted**: Qwen на vLLM через `ChatOpenAI` с `base_url`. Ключа
  нет, но библиотека требует непустую строку — отсюда `RUDIK_LLM_API_KEY=EMPTY`.
- **Qwen иногда отдаёт `<think>…</think>` прямо в ответе** — `clean_answer`
  в `agent/graph.py` это вырезает.
- **User-Agent должен быть ASCII** — httpx кодирует заголовки в latin-1.
- **Ссылки со страницы собираются до `html.clean()`** — чистка выкидывает
  шапку с навигацией.
- **`<header>` внутри карточки сотрудника (`.uk-comment-header`) удалять
  нельзя** — там имя. Чистится только шапка сайта.
- **Тексты и комментарии в коде — на русском**, как и весь интерфейс.
- **Голосовые зависимости опциональны**: код должен деградировать до текста
  и браузерного синтеза, а не падать.
- **Две модели распознавания, и это намеренно**: Vosk слушает поток постоянно
  и ловит обращение, GigaAM включается только на выделенную реплику. Гонять
  GigaAM на весь поток нельзя — вырастет задержка.
- **Распознавание блокирующее** — вызывать только через `asyncio.to_thread`,
  иначе встанет весь событийный цикл.
- **Экран — киоск по макету**, а не чат: одно состояние на весь холст.
  Состояния перечислены в `Screen` (`lib/rudik-store.ts`), проверять их удобно
  через `/?screen=<состояние>`.
- **Микрофон требует https или localhost** и жеста пользователя. Сертификат
  для доступа по сети Vite подхватывает из `frontend/certs/`.

## Данные

`backend/data/` не коммитится. Если индекс пуст, `/api/health` покажет
`chunks: 0`, а поиск вернёт пустоту — нужно запустить скрапер.
