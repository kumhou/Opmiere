"""Suggest keep-ranges by inverting silencedetect — cut dead air.

Uses the same ffmpeg silencedetect path as analyze_audio, then returns the
complementary *keep* intervals (with optional pad into silence). Pure ffmpeg;
no ML. Agent can trim clips or split from these numbers.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["suggest_keep_ranges"]

_SILENCE_START = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)")


def suggest_keep_ranges(
    path: Path | str,
    *,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.4,
    pad_seconds: float = 0.08,
    min_keep_seconds: float = 0.2,
) -> dict[str, Any]:
    """Return keep ranges (speech/sound) between silences.

    ``pad_seconds`` extends each keep a little into adjacent silence so cuts
    do not clip consonants. Ranges shorter than ``min_keep_seconds`` drop.
    """
    require_ffmpeg_tools()
    path = Path(path)
    info = probe(path)
    if not info.has_audio:
        raise ValueError(f"{path} has no audio stream")
    duration = float(info.duration_seconds)

    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(path),
            "-map", "a:0",
            "-af", f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_seconds}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    text = proc.stderr
    starts = [float(m.group(1)) for m in _SILENCE_START.finditer(text)]
    ends = [float(m.group(1)) for m in _SILENCE_END.finditer(text)]

    silences: list[dict[str, float]] = []
    ei = 0
    for s in starts:
        if ei < len(ends) and ends[ei] >= s:
            e = min(ends[ei], duration)
            ei += 1
        else:
            e = duration
        silences.append({
            "start": s,
            "end": e,
            "duration": e - s,
        })

    if not silences:
        return {
            "path": str(path),
            "duration_seconds": duration,
            "silence_threshold_db": silence_threshold_db,
            "min_silence_seconds": min_silence_seconds,
            "pad_seconds": pad_seconds,
            "silences": [],
            "keep_ranges": [{
                "start": 0.0,
                "end": round(duration, 3),
                "duration": round(duration, 3),
            }],
        }

    keep: list[dict[str, float]] = []
    t = 0.0
    for sil in silences:
        k_end = min(duration, sil["start"] + pad_seconds)
        if k_end - t >= min_keep_seconds:
            keep.append({
                "start": round(t, 3),
                "end": round(k_end, 3),
                "duration": round(k_end - t, 3),
            })
        t = max(t, sil["end"] - pad_seconds)
    if duration - t >= min_keep_seconds:
        keep.append({
            "start": round(t, 3),
            "end": round(duration, 3),
            "duration": round(duration - t, 3),
        })

    return {
        "path": str(path),
        "duration_seconds": duration,
        "silence_threshold_db": silence_threshold_db,
        "min_silence_seconds": min_silence_seconds,
        "pad_seconds": pad_seconds,
        "silences": silences,
        "keep_ranges": keep,
    }
