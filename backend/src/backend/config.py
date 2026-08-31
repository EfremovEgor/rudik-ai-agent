"""Конфигурация Рудика. Все значения переопределяются через .env или окружение."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/backend/config.py -> backend/
PACKAGE_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_ROOT.parents[1]
DATA_DIR = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"),
        env_prefix="RUDIK_",
        env_file_encoding="utf-8",
        extra="ignore",
        # Без этого pydantic-settings пытается разобрать списки как JSON ещё до
        # валидаторов, и строка "a,b" из .env роняет запуск.
        enable_decoding=False,
    )

    # --- Языковая модель (self-hosted Qwen на vLLM, OpenAI-совместимый API) ---
    llm_base_url: str = "http://10.129.15.215:8000/v1"
    model: str = "qwen38-flash-next"
    # vLLM ключ не проверяет, но клиент OpenAI требует непустую строку.
    llm_api_key: str = "EMPTY"
    # Ответ киоска короткий: запас нужен только на случай, если модель
    # разговорится, — обрывать её на полуслове хуже, чем дать договорить.
    max_tokens: int = 400
    temperature: float = 0.3
    llm_timeout: float = 120.0
    # Рассуждения Qwen перед ответом. Выключены намеренно: модель тратила на них
    # полторы-пять секунд, а киоску нужен ответ сразу. Качество и вызовы
    # инструментов при этом не пострадали.
    llm_thinking: bool = False
    # Сколько раз повторить запрос, если сервер модели ответил 5xx или оборвал связь.
    llm_retries: int = 2
    # Ходить ли к модели через системный прокси (HTTP_PROXY и компания).
    # По умолчанию нет: сервер стоит во внутренней сети, и прокси, настроенный
    # для выхода в интернет, отвечает на такие адреса 502.
    llm_trust_env: bool = False
    # Потолок на весь ответ агента, включая инструменты. Киоск в холле не может
    # держать человека у экрана дольше — лучше честно извиниться.
    agent_timeout: float = 45.0
    # Предохранитель против зацикливания «модель -> инструменты -> модель».
    agent_max_steps: int = 8
    # Пауза, после которой считаем, что у экрана уже другой человек, и
    # начинаем диалог с чистого листа. Иначе киоск тащит переписку месяцами:
    # модель видит свои старые ответы и повторяет их даже после смены промпта.
    dialog_ttl_s: float = 180.0

    # --- Сервер ---
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # --- Скрапер ---
    site_base: str = "https://academy.rudn.ru"
    crawl_delay: float = 0.4
    crawl_max_pages: int = 400
    # Заголовок должен быть ASCII — httpx кодирует его в latin-1.
    user_agent: str = (
        "RudikBot/1.0 (RUDN Engineering Academy assistant; +https://academy.rudn.ru/)"
    )
    # Ходить ли за страницами через системный прокси. По умолчанию нет — та же
    # беда, что и с сервером модели: прокси из окружения рвёт соединение,
    # и живой обход падает на первой же странице.
    scraper_trust_env: bool = False

    # --- RAG ---
    embeddings: str = "fastembed"
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    top_k: int = 6
    chunk_chars: int = 1200
    chunk_overlap: int = 200

    # --- Голос ---
    # Распознавание: GigaAM v3 (E2E RNN-T) в ONNX — лучший русский из доступных.
    asr_model: str = "gigaam-v3-e2e-rnnt"
    # int8 быстрее и меньше весит; пустая строка — исходная точность.
    asr_quantization: str = "int8"
    # Маленькая модель, которая всё время слушает поток и ловит обращение.
    hotword_model: str = "vosk-model-small-ru-0.22"
    # Ловить обращение отдельным распознавателем, которому разрешено только
    # само имя. В шумном холле свободное распознавание слышит вместо «Рудик»
    # то «пороге», то «рубят»; с ограниченной грамматикой промахов нет.
    # Выключать имеет смысл, только если имя вне словаря модели Vosk.
    hotword_grammar: bool = True
    # Порог уверенности для обращения. На записях настоящее «Рудик» всегда
    # получает единицу, случайные совпадения — от нуля до 0.6, так что порог
    # режет половину ложных срабатываний и ни одного настоящего.
    hotword_confidence: float = 0.9
    # Сколько ответ защищён от перехвата. Сразу после вопроса в канале ещё
    # звучит его хвост, и без паузы ответ обрывался на первых буквах.
    interrupt_guard_ms: int = 1500
    # Сколько звука до момента срабатывания дописываем к реплике.
    stream_preroll_ms: int = 2000
    # Предохранитель: реплика не может длиться дольше.
    stream_max_utterance_s: float = 15.0
    # Сколько держится тишина, прежде чем поверить Vosk, что реплика кончилась.
    # Меньше — ответ быстрее, но человека обрывают на раздумье посреди вопроса.
    stream_endpoint_hold_ms: int = 600
    # Страховочная пауза, после которой реплика закрывается принудительно.
    # Конец фразы определяет Vosk — он слышит, что фраза не закончена, а голая
    # громкость этого не знает и обрывает человека на раздумье. Поэтому порог
    # заведомо больше обычной паузы в речи.
    stream_silence_ms: int = 1200
    # silero | piper | edge | none. Silero и Piper считают у себя: синтез фразы
    # занимает доли секунды, тогда как edge ходит в облако и иногда отвечает
    # через двадцать. Silero живее по интонации и сам расставляет ударения.
    tts_backend: str = "silero"
    # Голоса Silero v4: aidar и eugene мужские, baya, kseniya, xenia женские.
    silero_voice: str = "eugene"
    silero_model_url: str = "https://models.silero.ai/models/tts/ru/v5_5_ru.pt"
    # 48000 звучит чище, 24000 и 8000 тоже поддерживаются.
    silero_sample_rate: int = 48000
    # Синтез на видеокарте. Требует torch со сборкой под CUDA; на процессоре
    # Silero и так работает в разы быстрее реального времени.
    silero_cuda: bool = False
    # Голос Piper из каталога rhasspy/piper-voices, скачивается при первом пуске.
    piper_voice: str = "ru_RU-ruslan-medium"
    # Синтез Piper на видеокарте. Требует onnxruntime-gpu вместо обычной сборки.
    piper_cuda: bool = False
    # Голос edge-tts — на случай, если tts_backend вернут на edge.
    tts_voice: str = "ru-RU-DmitryNeural"
    tts_rate: str = "+8%"
    wake_word: str = "рудик"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # --- Пути ---
    @property
    def data_dir(self) -> Path:
        return DATA_DIR

    @property
    def raw_dir(self) -> Path:
        return DATA_DIR / "raw"

    @property
    def index_dir(self) -> Path:
        return DATA_DIR / "index"

    @property
    def models_dir(self) -> Path:
        return DATA_DIR / "models"

    @property
    def documents_path(self) -> Path:
        return DATA_DIR / "documents.jsonl"

    @property
    def structured_path(self) -> Path:
        return DATA_DIR / "structured.json"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    return settings
