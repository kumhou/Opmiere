"""ffprobe wrapper: inspect a media file's real fps/resolution/duration/audio.

Used at import time to fill in Media fields honestly (never guessed) and to
validate that a source's frame rate matches the project timebase — P0's FFmpeg
backend assumes matching fps (see render/ffmpeg.py) and this is where that
assumption is checked.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    pass


def require_ffmpeg_tools() -> None:
    missing = [exe for exe in ("ffmpeg", "ffprobe") if shutil.which(exe) is None]
    if missing:
        raise FFmpegNotFoundError(
            f"required tool(s) not found on PATH: {', '.join(missing)}"
        )


@dataclass
class ProbeResult:
    duration_seconds: float
    fps: float | None  # None if no video stream
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


def _parse_rate(rate: str) -> float:
    # ffprobe reports frame rates as "num/den", e.g. "30000/1001".
    if "/" in rate:
        num, den = rate.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    return float(rate)


def probe(path: Path) -> ProbeResult:
    require_ffmpeg_tools()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    proc = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{proc.stderr}")

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration_str = fmt.get("duration") or (video_stream or {}).get("duration")
    if duration_str is None:
        raise RuntimeError(f"ffprobe returned no duration for {path}")
    duration_seconds = float(duration_str)

    if video_stream is None:
        return ProbeResult(duration_seconds, None, None, None, False, has_audio)

    fps = _parse_rate(video_stream.get("r_frame_rate", "0/1"))
    width = video_stream.get("width")
    height = video_stream.get("height")
    return ProbeResult(duration_seconds, fps, width, height, True, has_audio)
