"""Насколько надёжно ловится обращение «Рудик» в реальных условиях.

Берёт записанные реплики, портит их так, как их портит холл — тише, дальше,
с гулом — и прогоняет через ту же связку Vosk + нечёткое сравнение, что и
живой канал. Показывает, на каком уровне шума обращение начинает теряться
и что при этом слышит Vosk.

    uv run python scripts/bench_wake.py
"""

import json
import sys
from pathlib import Path

import numpy as np

from backend.voice import asr
from backend.voice.hotword import HotwordStream, heard_wake_word

CACHE = Path(__file__).parent / ".bench_audio"
FRAME = 1024  # 64 мс при 16 кГц

# Громкость речи и уровень фонового гула. Чем меньше gain, тем дальше человек
# от микрофона; noise — шум холла относительно полной шкалы.
CONDITIONS = [
    ("тихий зал, рядом", 1.0, 0.0),
    ("тихий зал, поодаль", 0.35, 0.0),
    ("лёгкий гул", 1.0, 0.005),
    ("обычный холл", 0.6, 0.01),
    ("шумный холл", 0.6, 0.03),
    ("шумный холл, поодаль", 0.3, 0.03),
]


def degrade(samples: np.ndarray, gain: float, noise: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noisy = samples * gain + rng.normal(0, noise, samples.shape).astype(np.float32)
    return np.clip(noisy, -1.0, 1.0)


def feed(samples: np.ndarray) -> tuple[bool, str]:
    """Гоняет запись через Vosk кадр за кадром, как это делает канал."""
    stream = HotwordStream()
    if not stream.ready:
        raise SystemExit("Vosk не загрузился — смотрите /api/health")

    pcm = (samples * 32767).astype(np.int16)
    heard, last = False, ""
    for start in range(0, len(pcm), FRAME):
        text, _ = stream.accept(pcm[start : start + FRAME].tobytes())
        if text:
            last = text
        if text and heard_wake_word(text):
            heard = True
            break
    return heard, last or stream.flush()


def main() -> None:
    clips = sorted(CACHE.glob("*.mp3"))
    if not clips:
        raise SystemExit(f"Нет записей в {CACHE} — сначала запустите bench_stt.py")

    report = {}
    for label, gain, noise in CONDITIONS:
        hits, misses = 0, []
        for index, clip in enumerate(clips):
            samples = asr.decode_audio(clip.read_bytes())
            heard, text = feed(degrade(samples, gain, noise, seed=index))
            if heard:
                hits += 1
            else:
                misses.append({"clip": clip.name, "vosk": text})
        report[label] = {"hits": hits, "total": len(clips), "misses": misses}
        print(f"{label:24} {hits}/{len(clips)}")
        for miss in misses[:3]:
            print(f"    промах: {miss['clip']} -> Vosk услышал: {miss['vosk'][:70]!r}")

    Path(__file__).with_name("bench_wake.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )


main()
sys.exit(0)
