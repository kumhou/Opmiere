"""Audio waveform peaks for timeline display (ffmpeg PCM sample, no ML)."""

from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["extract_waveform_peaks", "waveform_cache_path", "load_cached_peaks", "save_cached_peaks"]


def waveform_cache_path(analysis_dir: Path, media_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in media_id)
    return Path(analysis_dir) / "waveforms" / f"{safe}.json"


def load_cached_peaks(analysis_dir: Path, media_id: str) -> dict[str, Any] | None:
    path = waveform_cache_path(analysis_dir, media_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_cached_peaks(analysis_dir: Path, media_id: str, data: dict[str, Any]) -> Path:
    path = waveform_cache_path(analysis_dir, media_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def extract_waveform_peaks(
    path: Path | str,
    *,
    num_peaks: int = 200,
    sample_rate: int = 8000,
) -> dict[str, Any]:
    """Return normalized peak envelope [0..1] for mono mix of ``path``.

    Uses ffmpeg to decode mono f32le at a low sample rate, then buckets
    max(|sample|) into ``num_peaks`` columns.
    """
    require_ffmpeg_tools()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if num_peaks < 8 or num_peaks > 4000:
        raise ValueError("num_peaks must be in [8, 4000]")

    info = probe(path)
    if not info.has_audio:
        return {
            "path": str(path.resolve()),
            "has_audio": False,
            "duration_seconds": info.duration_seconds,
            "num_peaks": 0,
            "peaks": [],
            "sample_rate": sample_rate,
        }

    with tempfile.TemporaryDirectory(prefix="opmiere_wave_") as td:
        raw = Path(td) / "mono.f32"
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-i", str(path),
                "-vn", "-ac", "1", "-ar", str(sample_rate),
                "-f", "f32le", str(raw),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not raw.exists():
            raise RuntimeError(
                f"waveform extract failed:\n{(proc.stderr or '')[-1500:]}"
            )
        data = raw.read_bytes()

    n_samples = len(data) // 4
    if n_samples == 0:
        return {
            "path": str(path.resolve()),
            "has_audio": True,
            "duration_seconds": info.duration_seconds,
            "num_peaks": 0,
            "peaks": [],
            "sample_rate": sample_rate,
        }

    # Unpack as little-endian floats
    samples = struct.unpack(f"<{n_samples}f", data[: n_samples * 4])
    bucket = max(1, n_samples // num_peaks)
    peaks: list[float] = []
    for i in range(num_peaks):
        start = i * bucket
        end = min(n_samples, start + bucket)
        if start >= n_samples:
            peaks.append(0.0)
            continue
        chunk = samples[start:end]
        peak = max(abs(x) for x in chunk) if chunk else 0.0
        peaks.append(float(peak))

    # Normalize to 0..1
    mx = max(peaks) if peaks else 0.0
    if mx > 1e-9:
        peaks = [min(1.0, p / mx) for p in peaks]
    else:
        peaks = [0.0] * len(peaks)

    return {
        "path": str(path.resolve()),
        "has_audio": True,
        "duration_seconds": float(info.duration_seconds or 0.0),
        "num_peaks": len(peaks),
        "peaks": [round(p, 4) for p in peaks],
        "sample_rate": sample_rate,
        "samples": n_samples,
    }
