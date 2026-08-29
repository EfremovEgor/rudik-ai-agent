"""Схемы запросов и ответов API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)


class ChatResponse(BaseModel):
    text: str
    sources: list[str] = []
    session_id: str = "default"


class WakeInfo(BaseModel):
    detected: bool
    command: str = ""
    matched: str = ""
    score: float = 0.0


class TranscriptResponse(BaseModel):
    text: str
    duration: float = 0.0
    wake: WakeInfo


class VoiceAnswer(BaseModel):
    """Полный цикл: что услышали, что ответили и озвучка ответа."""

    question: str
    answer: str = ""
    spoken: str = ""
    sources: list[str] = []
    wake: WakeInfo
    audio: str | None = None
    audio_format: str = "audio/mpeg"
    session_id: str = "default"


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    wake_word: str
    llm: dict[str, Any]
    knowledge_base: dict[str, Any]
    stt: dict[str, Any]
    hotword: dict[str, Any]
    tts: dict[str, Any]
