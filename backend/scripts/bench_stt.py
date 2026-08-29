"""Замер качества распознавания русской речи.

Синтезирует набор типичных вопросов двумя голосами, прогоняет их через
faster-whisper и считает WER. Аудио кэшируется, так что повторные прогоны
быстрые.

    uv run python scripts/bench_stt.py small
    uv run python scripts/bench_stt.py medium
"""

import asyncio
import io
import json
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import edge_tts
from faster_whisper import WhisperModel

from backend.voice.stt import domain_prompt

PHRASES = [
    "Рудик, скажи где кабинет Салтыковой?",
    "Рудик, кто заведует кафедрой механики и процессов управления?",
    "Рудик, где сидит Разумный Юрий Николаевич?",
    "Рудик, какие направления бакалавриата есть в академии?",
    "Рудик, когда работает приёмная комиссия?",
    "Рудик, что нового в Инженерной академии?",
    "Рудик, как найти Дмитриченкову Светлану Владимировну?",
    "Рудик, какой кабинет у Котельникова?",
]
VOICES = ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"]
CACHE = Path(__file__).parent / ".bench_audio"


async def synth(text: str, voice: str, path: Path) -> None:
    if path.exists():
        return
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    path.write_bytes(bytes(audio))


def normalize(text: str) -> str:
    keep = "".join(c for c in text.lower().replace("ё", "е") if c.isalnum() or c.isspace())
    return " ".join(keep.split())


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    matcher = SequenceMatcher(None, ref, hyp)
    correct = sum(block.size for block in matcher.get_matching_blocks())
    return round(max(0, len(ref) - correct) / max(1, len(ref)), 3)


async def main(model_names: list[str]) -> None:
    CACHE.mkdir(exist_ok=True)
    clips = []
    for index, phrase in enumerate(PHRASES):
        for voice in VOICES:
            path = CACHE / f"{index}-{voice.split('-')[2]}.mp3"
            await synth(phrase, voice, path)
            clips.append((phrase, path))

    report = {}
    for model_name in model_names:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        started = time.monotonic()
        rows, total = [], 0.0
        for phrase, path in clips:
            segments, _ = model.transcribe(
                io.BytesIO(path.read_bytes()),
                language="ru",
                beam_size=5,
                vad_filter=True,
                initial_prompt=domain_prompt(),
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            score = wer(phrase, text)
            total += score
            rows.append({"ref": phrase, "hyp": text, "wer": score})
        report[model_name] = {
            "wer": round(total / len(clips), 3),
            "seconds": round(time.monotonic() - started, 1),
            "rows": rows,
        }
        del model

    Path(__file__).with_name(f"bench_{model_names[0]}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("done")


asyncio.run(main(sys.argv[1:] or ["small"]))
