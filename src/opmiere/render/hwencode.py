"""Detect NVIDIA NVENC and build encode argv for FFmpeg delivery path.

Filter_graph still runs on CPU for compatibility; win is encode (+ optional
hw decode). Falls back to libx264 when NVENC is missing or fails probe.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from typing import Any

__all__ = ["nvenc_available", "video_encode_args", "hwaccel_input_args"]


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=8,
    )
    if proc.returncode != 0:
        return False
    if "h264_nvenc" not in (proc.stdout or ""):
        return False
    # Smoke: encode one black frame (may fail on headless without GPU)
    proc2 = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-f", "lavfi",
            "-i", "color=c=black:s=64x64:d=0.1:r=30",
            "-c:v", "h264_nvenc", "-frames:v", "1", "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=20,
    )
    return proc2.returncode == 0


def video_encode_args(*, prefer_nvenc: bool = True) -> list[str]:
    """Return -c:v ... args (no -map)."""
    if prefer_nvenc and nvenc_available():
        # p4 = medium quality/speed; cq similar spirit to CRF
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-rc", "vbr",
            "-cq", "23",
            "-b:v", "0",
            "-pix_fmt", "yuv420p",
        ]
    return [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
    ]


def hwaccel_input_args(*, prefer_cuda: bool = True) -> list[str]:
    """Optional global decode accel before -i (best-effort)."""
    if not prefer_cuda or not nvenc_available():
        return []
    # Safe default: try CUDA decode; filters still often download to system mem
    return ["-hwaccel", "cuda"]


def encode_status() -> dict[str, Any]:
    return {
        "nvenc": nvenc_available(),
        "video_encode": video_encode_args(),
        "hwaccel_input": hwaccel_input_args(),
    }
