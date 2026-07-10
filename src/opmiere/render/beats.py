"""Lightweight beat / onset anchors from music (ffmpeg + pure Python).

No aubio/librosa dependency. Decode mono PCM, build an energy envelope,
peak-pick with a BPM-aware refractory period. Good enough for B-roll /
cutaway landing points — not a full DJ beatgrid.
"""

from __future__ import annotations

import math
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["detect_beats"]

_SAMPLE_RATE = 22050


def _decode_mono_f32(path: Path, max_seconds: float | None = 180.0) -> list[float]:
    require_ffmpeg_tools()
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-ac", "1", "-ar", str(_SAMPLE_RATE),
        "-f", "f32le",
    ]
    if max_seconds is not None:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"failed to decode audio for beat detect:\n"
            f"{(proc.stderr or b'').decode('utf-8', errors='replace')[-1500:]}"
        )
    raw = proc.stdout
    n = len(raw) // 4
    return list(struct.unpack(f"<{n}f", raw[: n * 4]))


def _envelope(samples: list[float], win: int, hop: int) -> list[float]:
    env: list[float] = []
    i = 0
    n = len(samples)
    while i + win <= n:
        chunk = samples[i : i + win]
        # RMS
        acc = 0.0
        for x in chunk:
            acc += x * x
        env.append(math.sqrt(acc / win))
        i += hop
    return env


def _peak_pick(
    env: list[float],
    hop_seconds: float,
    *,
    min_bpm: float = 70.0,
    max_bpm: float = 180.0,
    sensitivity: float = 1.15,
) -> list[float]:
    if len(env) < 8:
        return []
    # local mean for adaptive threshold
    radius = max(2, int(0.25 / hop_seconds))  # ~250ms neighborhood
    peaks: list[tuple[int, float]] = []
    for i in range(1, len(env) - 1):
        if env[i] < env[i - 1] or env[i] < env[i + 1]:
            continue
        lo = max(0, i - radius)
        hi = min(len(env), i + radius + 1)
        local = env[lo:hi]
        mean = sum(local) / len(local)
        if env[i] >= mean * sensitivity and env[i] > 1e-5:
            peaks.append((i, env[i]))

    # min interval from max BPM
    min_interval = 60.0 / max_bpm
    min_hops = max(1, int(min_interval / hop_seconds))
    filtered: list[tuple[int, float]] = []
    last_i = -10**9
    # sort by strength then enforce spacing chronologically
    peaks_by_time = sorted(peaks, key=lambda p: p[0])
    for i, strength in peaks_by_time:
        if i - last_i >= min_hops:
            filtered.append((i, strength))
            last_i = i
        elif filtered and strength > filtered[-1][1]:
            # stronger peak wins in the window
            filtered[-1] = (i, strength)
            last_i = i

    times = [i * hop_seconds for i, _ in filtered]
    # drop ultra-slow pairs below min_bpm by thinning if density absurd
    return times


def _estimate_bpm(times: list[float]) -> float | None:
    if len(times) < 3:
        return None
    intervals = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    intervals = [x for x in intervals if 60.0 / 180.0 <= x <= 60.0 / 70.0]
    if not intervals:
        return None
    intervals.sort()
    mid = intervals[len(intervals) // 2]
    if mid <= 0:
        return None
    return round(60.0 / mid, 1)


def detect_beats(
    path: Path | str,
    *,
    max_seconds: float | None = 180.0,
    hop_ms: float = 20.0,
    window_ms: float = 40.0,
    sensitivity: float = 1.15,
    min_bpm: float = 70.0,
    max_bpm: float = 180.0,
) -> dict[str, Any]:
    """Return beat/onset times in seconds for ``path`` (audio or video)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = probe(path)
    if not info.has_audio:
        raise ValueError(f"{path} has no audio stream for beat detection")

    samples = _decode_mono_f32(path, max_seconds=max_seconds)
    hop = max(1, int(_SAMPLE_RATE * hop_ms / 1000.0))
    win = max(hop, int(_SAMPLE_RATE * window_ms / 1000.0))
    env = _envelope(samples, win, hop)
    hop_s = hop / _SAMPLE_RATE
    times = _peak_pick(
        env, hop_s, min_bpm=min_bpm, max_bpm=max_bpm, sensitivity=sensitivity,
    )
    bpm = _estimate_bpm(times)
    duration = float(info.duration_seconds)
    if max_seconds is not None:
        duration = min(duration, float(max_seconds))

    return {
        "path": str(path.resolve()),
        "duration_seconds": duration,
        "beat_times": [round(t, 3) for t in times],
        "beat_count": len(times),
        "bpm_estimate": bpm,
        "hop_ms": hop_ms,
        "sensitivity": sensitivity,
        "agent_note": (
            "Energy-onset grid, not a studio beatgrid. Prefer stronger "
            "phrase points (every 4–8 beats) for cutaways."
        ),
    }


def phrase_anchors(
    beat_times: list[float],
    *,
    every_n: int = 4,
    offset: int = 0,
) -> list[float]:
    """Take every Nth beat as a phrase landing (default 4 = bar-ish)."""
    if every_n < 1:
        every_n = 1
    return [
        beat_times[i]
        for i in range(offset, len(beat_times), every_n)
    ]
