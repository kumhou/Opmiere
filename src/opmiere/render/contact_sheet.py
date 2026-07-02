"""contact_sheet: the agent's eyes into a clip, kept cheap on purpose.

ARCHITECTURE.md 5.10's agent-director loop needs the agent to *see* a
generated fragment's motion/composition to judge it - but sending full-res
frames (or many of them) for every fragment burns tokens fast (JH's explicit
concern). A single small tiled grid of evenly-spaced thumbnails, sampled
across the whole clip, gives the agent the shot's motion arc in one image
instead of N large ones.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .probe import ProbeResult, probe, require_ffmpeg_tools


def make_contact_sheet(
    path: Path, output_path: Path, *, cols: int = 3, rows: int = 3, tile_width: int = 160,
) -> Path:
    """Sample cols*rows frames evenly across `path`'s duration and tile them
    into one small grid image at output_path. Raises if the file has no
    video stream (there's nothing to show)."""
    require_ffmpeg_tools()
    path = Path(path)
    output_path = Path(output_path)
    info: ProbeResult = probe(path)
    if not info.has_video:
        raise ValueError(f"{path} has no video stream - nothing to make a contact sheet from")

    n_tiles = cols * rows
    total_frames = max(1, round(info.duration_seconds * (info.fps or 1)))
    # Evenly spaced sample interval; at least 1 so a very short clip (fewer
    # frames than tiles) still produces *a* sheet instead of a select
    # expression that matches nothing.
    interval = max(1, total_frames // n_tiles)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-vf", f"select='not(mod(n\\,{interval}))',scale={tile_width}:-1,tile={cols}x{rows}",
        "-frames:v", "1", "-update", "1", "-vsync", "vfr",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to build contact sheet for {path}:\n{proc.stderr}")
    return output_path
