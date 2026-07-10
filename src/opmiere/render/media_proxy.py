"""Per-asset low-res proxies for the media bin (scrub, not delivery)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["build_media_proxy"]


def build_media_proxy(
    src: Path | str,
    dest: Path | str,
    *,
    height: int = 480,
    crf: int = 28,
    preset: str = "veryfast",
    audio: bool = True,
) -> dict[str, Any]:
    """Encode a low-res H.264 proxy of ``src`` to ``dest``.

    Video scaled to ``height`` (even), aspect preserved. Audio AAC mono when
    present and ``audio`` is True. Raises on missing tools or encode failure.
    """
    require_ffmpeg_tools()
    src = Path(src)
    dest = Path(dest)
    if not src.exists():
        raise FileNotFoundError(src)
    if height < 72 or height > 1080:
        raise ValueError("height must be in [72, 1080]")

    info = probe(src)
    dest.parent.mkdir(parents=True, exist_ok=True)

    h = int(height) // 2 * 2
    vf = f"scale=-2:{h}"
    cmd: list[str] = [
        "ffmpeg", "-y", "-hide_banner", "-i", str(src),
    ]
    if info.has_video:
        cmd += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", preset, "-crf", str(crf)]
    else:
        cmd += ["-vn"]

    if audio and info.has_audio:
        cmd += ["-c:a", "aac", "-ac", "1", "-b:a", "96k"]
    else:
        cmd += ["-an"]

    cmd.append(str(dest))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(
            f"media proxy encode failed for {src}:\n{(proc.stderr or '')[-2000:]}"
        )
    after = probe(dest)
    return {
        "path": str(dest.resolve()),
        "source": str(src.resolve()),
        "width": after.width,
        "height": after.height,
        "duration_seconds": after.duration_seconds,
        "has_audio": after.has_audio,
        "proxy_height_request": h,
    }
