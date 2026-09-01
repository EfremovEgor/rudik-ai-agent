"""Замер качества распознавания русской речи.

Синтезирует набор типичных вопросов двумя голосами, прогоняет их через
распознавание и считает WER. Аудио кэшируется, повторные прогоны быстрые.

    uv run python scripts/bench_stt.py
"""

import asyncio
import json
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import edge_tts
from backend.voice import asr

PHRASES = [
    "Патрис, скажи где кабинет Салтыковой?",
    "Патрис, кто заведует кафедрой механики и процессов управления?",
    "Патрис, где сидит Разумный Юрий Николаевич?",
    "Патрис, какие направления бакалавриата есть в академии?",
    "Патрис, когда работает приёмная комиссия?",
    "Патрис, что нового в Инженерной академии?",
    "Патрис, как найти Дмитриченкову Светлану Владимировну?",
    "Патрис, какой кабинет у Котельникова?",
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
    keep = "".join(
        c for c in text.lower().replace("ё", "е") if c.isalnum() or c.isspace()
    )
    return " ".join(keep.split())


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    matcher = SequenceMatcher(None, ref, hyp)
    correct = sum(block.size for block in matcher.get_matching_blocks())
    return round(max(0, len(ref) - correct) / max(1, len(ref)), 3)


async def main() -> None:
    CACHE.mkdir(exist_ok=True)
    clips = []
    for index, phrase in enumerate(PHRASES):
        for voice in VOICES:
            path = CACHE / f"{index}-{voice.split('-')[2]}.mp3"
            await synth(phrase, voice, path)
            clips.append((phrase, path))

    asr.get_model()
    started = time.monotonic()
    rows, total = [], 0.0
    for phrase, path in clips:
        samples = asr.decode_audio(path.read_bytes())
        text = asr.transcribe_pcm(samples)
        score = wer(phrase, text)
        total += score
        rows.append({"ref": phrase, "hyp": text, "wer": score})

    report = {
        "model": asr.status()["model"],
        "wer": round(total / len(clips), 3),
        "seconds": round(time.monotonic() - started, 1),
        "clips": len(clips),
        "rows": rows,
    }
    Path(__file__).with_name("bench_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    perfect = sum(1 for row in rows if row["wer"] == 0)
    print(f"{report['model']}: WER {report['wer']}, идеально {perfect}/{len(rows)}")
    for row in rows:
        if row["wer"]:
            print(f"  {row['wer']:.2f} {row['ref']}")
            print(f"       -> {row['hyp']}")


asyncio.run(main())
sys.exit(0)
