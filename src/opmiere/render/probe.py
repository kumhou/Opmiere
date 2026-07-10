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
    sample_rate: int | None = None  # first audio stream, if any


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
        raise FileNotFoundError(
            f"media file not found: {path} "
            f"(check the path exists and is not a directory)"
        )

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
        raise RuntimeError(
            f"ffprobe failed on {path} (corrupt or unsupported media?):\n"
            f"{proc.stderr[-1500:] if proc.stderr else '(no stderr)'}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path}: {e}") from e
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    has_audio = audio_stream is not None
    sample_rate: int | None = None
    if audio_stream and audio_stream.get("sample_rate"):
        try:
            sample_rate = int(float(audio_stream["sample_rate"]))
        except (TypeError, ValueError):
            sample_rate = None

    duration_str = fmt.get("duration") or (video_stream or {}).get("duration")
    if duration_str is None and audio_stream:
        duration_str = audio_stream.get("duration")
    if duration_str is None:
        raise RuntimeError(
            f"ffprobe returned no duration for {path} "
            f"(empty or header-only file?)"
        )
    duration_seconds = float(duration_str)

    if video_stream is None:
        return ProbeResult(
            duration_seconds, None, None, None, False, has_audio, sample_rate,
        )

    fps = _parse_rate(video_stream.get("r_frame_rate", "0/1"))
    width = video_stream.get("width")
    height = video_stream.get("height")
    return ProbeResult(
        duration_seconds, fps, width, height, True, has_audio, sample_rate,
    )
