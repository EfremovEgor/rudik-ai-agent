"""Проверка голосового канала: льём в него запись и смотрим события.

uv run python scripts/check_stream.py путь-к-аудио.mp3
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import websockets
from backend.voice import asr

URL = "ws://127.0.0.1:8000/api/voice/stream?session_id=check"
FRAME_SAMPLES = 1024  # 64 мс при 16 кГц


async def main(path: Path) -> None:
    samples = asr.decode_audio(path.read_bytes())
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    # Хвост тишины, чтобы сработало определение конца реплики.
    pcm = np.concatenate([pcm, np.zeros(16000 * 2, dtype=np.int16)])
    print(f"аудио: {len(samples) / 16000:.1f} с, кадров: {len(pcm) // FRAME_SAMPLES}")

    started = time.monotonic()
    async with websockets.connect(URL, max_size=None) as ws:

        async def reader() -> None:
            async for message in ws:
                event = json.loads(message)
                mark = f"[{time.monotonic() - started:5.1f}s]"
                kind = event.get("type")
                if kind == "partial":
                    print(f"{mark} partial : {event['text']}")
                elif kind == "answer":
                    print(f"{mark} answer  : {event['answer'][:120]}")
                    print(f"{mark}           источники: {event['sources']}")
                    return
                elif kind == "error":
                    print(f"{mark} ОШИБКА  : {event['message'][:160]}")
                    return
                else:
                    print(
                        f"{mark} {kind:8}: {json.dumps(event, ensure_ascii=False)[:140]}"
                    )

        task = asyncio.create_task(reader())
        for index in range(0, len(pcm), FRAME_SAMPLES):
            if task.done():
                break
            await ws.send(pcm[index : index + FRAME_SAMPLES].tobytes())
            await asyncio.sleep(0.064)  # реальное время, как из браузера
        await asyncio.wait_for(task, timeout=180)


asyncio.run(
    main(
        Path(
            sys.argv[1]
            if len(sys.argv) > 1
            else "scripts/.bench_audio/0-DmitryNeural.mp3"
        )
    )
)
