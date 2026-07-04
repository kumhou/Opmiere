"""The agent's "ears" (ARCHITECTURE.md 5.10) — deterministic audio analysis.

make_contact_sheet gives an agent cheap eyes; this gives it cheap ears, the
missing half JH called out on the《雨后》dogfood ("音乐不够柔和" / "语音不太自然"
were caught by a human ear, not by the agent). Generated or mixed audio can't
be eyeballed, so this reports the things a mixing engineer would meter:

- volumedetect: mean/max sample level (dB) — quick "is it even audible/clipping".
- ebur128: integrated loudness (LUFS), loudness range (LU), true peak (dBFS) —
  the broadcast-standard numbers; e.g. music beds for speech typically sit
  well below the -14 LUFS streaming target, and a true peak near 0 warns of
  clipping after any further gain.
- silencedetect: dead-air regions with start/end/duration.
- optionally a waveform + spectrogram image — the numbers say "how loud", the
  picture says *where* and *what* (dynamics over time, hiss/harshness bands),
  and reading one image is far cheaper than reasoning over raw metrics alone.

All plain ffmpeg, no model calls, nothing leaves the machine.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["analyze_audio"]


def _parse_db(pattern: str, text: str) -> float | None:
    """First regex group as float, or None (e.g. '-inf' / missing) — a report
    with an honest gap beats a crash over a metric one clip can't have."""
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def analyze_audio(
    path: Path,
    image_path: Path | None = None,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.5,
) -> dict[str, Any]:
    """Meter ``path``'s audio; optionally render a waveform+spectrogram image.

    Returns duration, mean/max volume (dB), integrated loudness (LUFS),
    loudness range (LU), true peak (dBFS), and silence regions longer than
    ``min_silence_seconds`` below ``silence_threshold_db``. When
    ``image_path`` is given, also writes a stacked waveform-over-spectrogram
    PNG there and includes the path in the result.
    """
    require_ffmpeg_tools()
    path = Path(path)
    result = probe(path)
    if not result.has_audio:
        raise ValueError(f"{path} has no audio stream to analyze")

    metrics_cmd = [
        "ffmpeg", "-i", str(path),
        "-map", "a:0", "-af",
        f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_seconds},"
        "ebur128=peak=true,volumedetect",
        "-f", "null", "-",
    ]
    proc = subprocess.run(metrics_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio analysis failed (exit {proc.returncode}):\n{proc.stderr}"
        )
    stderr = proc.stderr

    # ebur128's per-100ms progress lines also contain "I:"/"LRA:" — only the
    # final Summary block (everything after the last "Summary:") is the
    # whole-file verdict.
    summary = stderr[stderr.rfind("Summary:"):]

    silences: list[dict[str, float]] = []
    for m in re.finditer(
        r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", stderr
    ):
        end_s, duration_s = float(m.group(1)), float(m.group(2))
        silences.append(
            {
                "start_seconds": round(end_s - duration_s, 3),
                "end_seconds": round(end_s, 3),
                "duration_seconds": round(duration_s, 3),
            }
        )
    # A silence_start with no matching silence_end = silent through EOF.
    starts = re.findall(r"silence_start: (-?[\d.]+)", stderr)
    if len(starts) > len(silences):
        start_s = max(0.0, float(starts[-1]))
        silences.append(
            {
                "start_seconds": round(start_s, 3),
                "end_seconds": round(result.duration_seconds, 3),
                "duration_seconds": round(result.duration_seconds - start_s, 3),
            }
        )

    report: dict[str, Any] = {
        "duration_seconds": result.duration_seconds,
        "mean_volume_db": _parse_db(r"mean_volume: (-?[\d.]+) dB", stderr),
        "max_volume_db": _parse_db(r"max_volume: (-?[\d.]+) dB", stderr),
        "integrated_lufs": _parse_db(r"I:\s+(-?[\d.]+) LUFS", summary),
        "loudness_range_lu": _parse_db(r"LRA:\s+(-?[\d.]+) LU", summary),
        "true_peak_dbfs": _parse_db(r"Peak:\s+(-?[\d.]+) dBFS", summary),
        "silences": silences,
        "image_path": None,
    }

    if image_path is not None:
        image_path = Path(image_path)
        image_cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-filter_complex",
            "[a:0]asplit=2[w][s];"
            "[w]showwavespic=s=1200x240,format=rgba[wv];"
            "[s]showspectrumpic=s=1200x360:legend=0,format=rgba[sp];"
            "[wv][sp]vstack=inputs=2",
            "-frames:v", "1", str(image_path),
        ]
        proc = subprocess.run(image_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg waveform/spectrogram render failed (exit {proc.returncode}):\n{proc.stderr}"
            )
        report["image_path"] = str(image_path)

    return report
