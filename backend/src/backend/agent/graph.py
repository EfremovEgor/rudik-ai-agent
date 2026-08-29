"""Граф агента Рудика на LangGraph: модель -> инструменты -> ответ."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from backend.agent.prompts import system_prompt
from backend.agent.tools import ALL_TOOLS
from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

# Сколько последних сообщений диалога держим в контексте.
HISTORY_LIMIT = 20


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


@dataclass
class ToolCallEvent:
    name: str
    args: dict[str, Any]


def build_model(settings: Settings) -> ChatOpenAI:
    """Клиент self-hosted модели: vLLM отдаёт OpenAI-совместимый API."""
    return ChatOpenAI(
        model=settings.model,
        base_url=settings.llm_base_url,
        # vLLM ключ не проверяет, но библиотека требует непустое значение.
        api_key=settings.llm_api_key or "EMPTY",
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        timeout=settings.llm_timeout,
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
        async with httpx.AsyncClient(timeout=5.0) as client:
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
        log.warning("InMemorySaver недоступен — диалог не будет помнить предыдущие реплики")
        return graph.compile()


def _config(session_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": session_id or "default"}}


async def answer(question: str, session_id: str = "default") -> dict[str, Any]:
    """Синхронный (не потоковый) ответ — используется голосовым каналом."""
    graph = build_graph()
    state = await graph.ainvoke(
        {"messages": [HumanMessage(content=question)]}, config=_config(session_id)
    )
    messages = state["messages"]
    text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = message.text() if callable(getattr(message, "text", None)) else str(message.content)
            break
    text = clean_answer(text)
    return {"text": text, "sources": extract_sources(text)}


async def stream_answer(question: str, session_id: str = "default") -> AsyncIterator[dict[str, Any]]:
    """Отдаёт события: вызовы инструментов и текст ответа по токенам."""
    graph = build_graph()
    seen_tools: set[str] = set()

    async for chunk, metadata in graph.astream(
        {"messages": [HumanMessage(content=question)]},
        config=_config(session_id),
        stream_mode="messages",
    ):
        if isinstance(chunk, AIMessage):
            for call in chunk.tool_calls or []:
                key = f"{call.get('name')}:{call.get('id')}"
                if call.get("name") and key not in seen_tools:
                    seen_tools.add(key)
                    yield {"type": "tool", "name": call["name"], "args": call.get("args", {})}

        text = _chunk_text(chunk)
        if text and metadata.get("langgraph_node") == "model":
            yield {"type": "token", "text": text}


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


def extract_sources(text: str) -> list[str]:
    """Достаёт ссылки, которые модель приписала в конце ответа."""
    return list(dict.fromkeys(re.findall(r"https?://[^\s)>\]]+", text)))


def strip_sources(text: str) -> str:
    """Убирает строки со ссылками — их не нужно озвучивать."""
    cleaned = re.sub(r"//\s*https?://\S+", "", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    return re.sub(r"\n{2,}", "\n", cleaned).strip()
