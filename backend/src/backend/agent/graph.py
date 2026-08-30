"""Граф агента Рудика на LangGraph: модель -> инструменты -> ответ."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from backend.agent.prompts import system_prompt
from backend.agent.tools import ALL_TOOLS
from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

# Сколько последних сообщений диалога держим в контексте.
HISTORY_LIMIT = 20

# Тексты для зала: посетителю у экрана не нужен ни код ошибки, ни трассировка.
BUSY_TEXT = (
    "Извините, сейчас я не могу ответить — сервер занят. "
    "Спросите, пожалуйста, ещё раз через минуту."
)
SLOW_TEXT = (
    "Извините, ответ занял слишком много времени. "
    "Задайте вопрос ещё раз, лучше покороче."
)


class AgentUnavailable(RuntimeError):
    """Модель не ответила: легла, не достучались или не уложились по времени.

    Отдельный тип нужен, чтобы отличить ожидаемый простой сервера от ошибки
    в нашем коде — первый показываем в зале, второй пишем в лог целиком.
    """


def _is_upstream_failure(exc: BaseException) -> bool:
    """Сервер модели недоступен, а не мы что-то напутали в запросе.

    Смотрим всю цепочку причин: LangGraph заворачивает исходное исключение,
    и наверху оказывается уже его обёртка.
    """
    try:
        import openai
    except ImportError:  # pragma: no cover — клиент всегда стоит вместе с langchain
        return False

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, openai.APIError):
            # 4xx — это наша ошибка в запросе, её прятать нельзя.
            status = getattr(current, "status_code", None)
            return not isinstance(status, int) or status >= 500
        current = current.__cause__ or current.__context__
    return False


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


@dataclass
class ToolCallEvent:
    name: str
    args: dict[str, Any]


def _http_clients(settings: Settings) -> dict[str, Any]:
    """Отдельные http-клиенты, если к модели нельзя ходить через прокси.

    Иначе httpx подхватывает HTTP_PROXY из окружения и заворачивает туда даже
    запросы во внутреннюю сеть — прокси на такой адрес отвечает 502.
    """
    if settings.llm_trust_env:
        return {}

    import httpx

    return {
        "http_client": httpx.Client(trust_env=False, timeout=settings.llm_timeout),
        "http_async_client": httpx.AsyncClient(
            trust_env=False, timeout=settings.llm_timeout
        ),
    }


def _extra_body(settings: Settings) -> dict[str, Any]:
    """Настройки шаблона чата, которых нет в OpenAI-совместимом API.

    Qwen по умолчанию сначала рассуждает и только потом отвечает: первый чанк
    с текстом приходил через полторы-пять секунд вместо четверти секунды.
    """
    if settings.llm_thinking:
        return {}
    return {"chat_template_kwargs": {"enable_thinking": False}}


def build_model(settings: Settings) -> ChatOpenAI:
    """Клиент self-hosted модели: vLLM отдаёт OpenAI-совместимый API."""
    return ChatOpenAI(
        **_http_clients(settings),
        extra_body=_extra_body(settings),
        model=settings.model,
        base_url=settings.llm_base_url,
        # vLLM ключ не проверяет, но библиотека требует непустое значение.
        api_key=settings.llm_api_key or "EMPTY",
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_retries,
        streaming=True,
    )


async def check_llm(settings: Settings | None = None) -> dict[str, Any]:
    """Быстрая проверка, отвечает ли сервер модели и есть ли на нём нужная модель."""
    import httpx

    settings = settings or get_settings()
    info: dict[str, Any] = {
        "base_url": settings.llm_base_url,
        "model": settings.model,
        "reachable": False,
        "models": [],
        "error": None,
    }
    try:
        async with httpx.AsyncClient(
            timeout=5.0, trust_env=settings.llm_trust_env
        ) as client:
            response = await client.get(f"{settings.llm_base_url.rstrip('/')}/models")
            response.raise_for_status()
            info["models"] = [item["id"] for item in response.json().get("data", [])]
            info["reachable"] = True
    except Exception as exc:
        info["error"] = str(exc)
    return info


@lru_cache(maxsize=1)
def build_graph() -> Any:
    """Компилирует граф один раз на процесс."""
    settings = get_settings()
    model = build_model(settings).bind_tools(ALL_TOOLS)

    def call_model(state: AgentState) -> dict[str, list[AnyMessage]]:
        history = state["messages"][-HISTORY_LIMIT:]
        messages = [SystemMessage(content=system_prompt()), *history]
        return {"messages": [model.invoke(messages)]}

    async def acall_model(state: AgentState) -> dict[str, list[AnyMessage]]:
        history = state["messages"][-HISTORY_LIMIT:]
        messages = [SystemMessage(content=system_prompt()), *history]
        return {"messages": [await model.ainvoke(messages)]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("model", acall_model)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")

    try:
        from langgraph.checkpoint.memory import InMemorySaver

        return graph.compile(checkpointer=InMemorySaver())
    except ImportError:  # без чекпойнтера просто не будет памяти диалога
        log.warning(
            "InMemorySaver недоступен — диалог не будет помнить предыдущие реплики"
        )
        return graph.compile()


def _config(session_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": session_id or "default"},
        # Один шаг — это один узел графа, так что на цикл «модель + инструменты»
        # уходит два. Берём с запасом от настроенного числа обращений к модели.
        "recursion_limit": max(2, get_settings().agent_max_steps * 2),
    }


async def answer(question: str, session_id: str = "default") -> dict[str, Any]:
    """Синхронный (не потоковый) ответ — используется голосовым каналом.

    Бросает `AgentUnavailable` с готовым текстом для зала, если сервер модели
    лёг или ответ не уложился в `agent_timeout`.
    """
    graph = build_graph()
    settings = get_settings()
    try:
        state = await asyncio.wait_for(
            graph.ainvoke(
                {"messages": [HumanMessage(content=question)]},
                config=_config(session_id),
            ),
            timeout=settings.agent_timeout,
        )
    except TimeoutError as exc:
        log.warning(
            "Агент не уложился в %s с — отвечаем извинением", settings.agent_timeout
        )
        raise AgentUnavailable(SLOW_TEXT) from exc
    except Exception as exc:
        if _is_upstream_failure(exc):
            # Стек тут не нужен: сервер модели лежит, чинить надо не код.
            log.warning("Сервер модели не ответил: %s", exc)
            raise AgentUnavailable(BUSY_TEXT) from exc
        raise
    messages = state["messages"]
    text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = (
                message.text()
                if callable(getattr(message, "text", None))
                else str(message.content)
            )
            break
    text = clean_answer(text)
    return {"text": text, "sources": extract_sources(text)}


async def stream_answer(
    question: str, session_id: str = "default"
) -> AsyncIterator[dict[str, Any]]:
    """Отдаёт события: вызовы инструментов и текст ответа по токенам."""
    graph = build_graph()
    seen_tools: set[str] = set()

    stream = graph.astream(
        {"messages": [HumanMessage(content=question)]},
        config=_config(session_id),
        stream_mode="messages",
    )
    async for chunk, metadata in _guarded(stream):
        if isinstance(chunk, AIMessage):
            for call in chunk.tool_calls or []:
                key = f"{call.get('name')}:{call.get('id')}"
                if call.get("name") and key not in seen_tools:
                    seen_tools.add(key)
                    yield {
                        "type": "tool",
                        "name": call["name"],
                        "args": call.get("args", {}),
                    }

        text = _chunk_text(chunk)
        if text and metadata.get("langgraph_node") == "model":
            yield {"type": "token", "text": text}


async def _guarded(stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
    """Оборачивает поток теми же правилами, что и обычный ответ.

    Потолок по времени тут на паузу между кусочками, а не на весь ответ:
    пока токены идут, поток живой и обрывать его незачем.
    """
    settings = get_settings()
    iterator = stream.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(
                iterator.__anext__(), timeout=settings.agent_timeout
            )
        except StopAsyncIteration:
            return
        except TimeoutError as exc:
            log.warning("Поток ответа замолчал дольше %s с", settings.agent_timeout)
            raise AgentUnavailable(SLOW_TEXT) from exc
        except Exception as exc:
            if _is_upstream_failure(exc):
                log.warning("Сервер модели не ответил: %s", exc)
                raise AgentUnavailable(BUSY_TEXT) from exc
            raise


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


# Qwen в режиме рассуждений иногда отдаёт размышления прямо в ответе.
THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def clean_answer(text: str) -> str:
    """Убирает служебные блоки рассуждений, если модель их не спрятала сама."""
    return THINK_BLOCK.sub("", text).strip()


THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


def _prefix_tail(text: str, tag: str) -> int:
    """Длина хвоста, который может оказаться началом тега.

    Тег приходит нарезанным на токены, поэтому «<thi» нельзя ни показать,
    ни выбросить — его придерживают до следующего кусочка.
    """
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return size
    return 0


class ThinkFilter:
    """Вырезает рассуждения модели из потока токенов.

    `clean_answer` работает по готовому тексту, а на экран киоска текст идёт
    по кусочкам — размышления нельзя показывать даже мельком.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> str:
        self._buffer += text
        shown: list[str] = []
        while self._buffer:
            if self._inside:
                end = self._buffer.find(THINK_CLOSE)
                if end == -1:
                    keep = _prefix_tail(self._buffer, THINK_CLOSE)
                    self._buffer = (
                        self._buffer[len(self._buffer) - keep :] if keep else ""
                    )
                    break
                self._buffer = self._buffer[end + len(THINK_CLOSE) :]
                self._inside = False
                continue

            start = self._buffer.find(THINK_OPEN)
            if start == -1:
                safe = len(self._buffer) - _prefix_tail(self._buffer, THINK_OPEN)
                shown.append(self._buffer[:safe])
                self._buffer = self._buffer[safe:]
                break
            shown.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(THINK_OPEN) :]
            self._inside = True
        return "".join(shown)

    def flush(self) -> str:
        """Остаток после конца потока: незакрытые рассуждения выбрасываем."""
        rest = "" if self._inside else self._buffer
        self._buffer = ""
        return rest


def extract_sources(text: str) -> list[str]:
    """Достаёт ссылки, которые модель приписала в конце ответа."""
    return list(dict.fromkeys(re.findall(r"https?://[^\s)>\]]+", text)))


def strip_sources(text: str) -> str:
    """Убирает строки со ссылками — их не нужно озвучивать."""
    cleaned = re.sub(r"//\s*https?://\S+", "", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    return re.sub(r"\n{2,}", "\n", cleaned).strip()
