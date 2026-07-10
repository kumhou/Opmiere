"""Lightweight camera/subject motion heuristics for asset cards.

Uses sampled grayscale frames (ffmpeg) and mean absolute differences — no
optical-flow dependency. Labels are coarse but agent-usable:
static | handheld | pan_left | pan_right | push_in | pull_out | dynamic.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["analyze_motion"]


def _png_gray_pixels(png_path: Path) -> tuple[int, int, list[int]]:
    """Load a grayscale PNG as flat pixel list (Pillow if present, else ffmpeg)."""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("L")
        w, h = im.size
        return w, h, list(im.getdata())
    except ImportError:
        pass
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(png_path), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("png decode failed")
    data = png_path.read_bytes()
    w = int.from_bytes(data[16:20], "big")
    h = int.from_bytes(data[20:24], "big")
    raw = proc.stdout
    if len(raw) < w * h:
        raise RuntimeError("raw frame size mismatch")
    return w, h, list(raw[: w * h])


def analyze_motion(
    path: Path | str,
    *,
    sample_fps: float = 5.0,
    max_frames: int = 40,
) -> dict[str, Any]:
    """Return motion energy, coarse label, and entry/exit hints."""
    path = Path(path)
    info = probe(path)
    if not info.has_video:
        return {
            "has_video": False,
            "label": "none",
            "energy_mean": 0.0,
            "energy_std": 0.0,
            "pan_bias": 0.0,
            "entry": "unknown",
            "exit": "unknown",
        }

    # Sample to temp files and analyze
    require_ffmpeg_tools()
    with tempfile.TemporaryDirectory(prefix="opmiere_motion_") as td:
        pattern = str(Path(td) / "f_%04d.png")
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-vf", f"fps={sample_fps},scale=160:-1,format=gray",
                "-frames:v", str(max_frames),
                pattern,
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg frame sample failed:\n{proc.stderr[-800:]}")
        paths = sorted(Path(td).glob("f_*.png"))
        if len(paths) < 2:
            return {
                "has_video": True,
                "label": "static",
                "energy_mean": 0.0,
                "energy_std": 0.0,
                "pan_bias": 0.0,
                "entry": "unknown",
                "exit": "unknown",
                "frames_sampled": len(paths),
            }

        diffs: list[float] = []
        left_diffs: list[float] = []
        right_diffs: list[float] = []
        luminances: list[float] = []
        prev: list[int] | None = None
        w = h = 0
        for fp in paths:
            w, h, pix = _png_gray_pixels(fp)
        luminances.append(sum(pix) / max(1, len(pix)))
        if prev is not None:
            n = min(len(prev), len(pix))
            total = 0
            left = right = 0
            left_n = right_n = 0
            half = w // 2
            for i in range(n):
                d = abs(pix[i] - prev[i])
                total += d
                x = i % w
                if x < half:
                    left += d
                    left_n += 1
                else:
                    right += d
                    right_n += 1
            diffs.append(total / n)
            left_diffs.append(left / max(1, left_n))
            right_diffs.append(right / max(1, right_n))
        prev = pix

        mean_e = sum(diffs) / len(diffs) if diffs else 0.0
        var = sum((d - mean_e) ** 2 for d in diffs) / len(diffs) if diffs else 0.0
        std_e = var ** 0.5
        mid = max(1, len(left_diffs) // 2)
        early_l = sum(left_diffs[:mid]) / mid
        early_r = sum(right_diffs[:mid]) / mid
        late_l = sum(left_diffs[mid:]) / max(1, len(left_diffs) - mid)
        late_r = sum(right_diffs[mid:]) / max(1, len(right_diffs) - mid)
        pan_bias = (late_r - late_l) - (early_r - early_l)

        if mean_e < 2.5:
            label = "static"
        elif mean_e < 6.0 and std_e < 3.0:
            label = "handheld"
        elif pan_bias > 1.5:
            label = "pan_right"
        elif pan_bias < -1.5:
            label = "pan_left"
        elif mean_e > 12:
            label = "dynamic"
        else:
            if luminances[-1] > luminances[0] * 1.08 and mean_e > 4:
                label = "push_in"
            elif luminances[0] > luminances[-1] * 1.08 and mean_e > 4:
                label = "pull_out"
            else:
                label = "handheld"

        head = luminances[: max(1, len(luminances) // 5)]
        tail = luminances[-max(1, len(luminances) // 5) :]
        entry = "fade_in" if head[-1] > head[0] + 15 and head[0] < 40 else (
            "motion_in" if (diffs[:3] and sum(diffs[:3]) / 3 > mean_e * 1.2) else "cut_in"
        )
        exit_ = "fade_out" if tail[0] > tail[-1] + 15 and tail[-1] < 40 else (
            "motion_out" if (diffs[-3:] and sum(diffs[-3:]) / 3 > mean_e * 1.2) else "cut_out"
        )

        return {
            "has_video": True,
            "label": label,
            "energy_mean": round(mean_e, 3),
            "energy_std": round(std_e, 3),
            "pan_bias": round(pan_bias, 3),
            "entry": entry,
            "exit": exit_,
            "frames_sampled": len(paths),
            "sample_fps": sample_fps,
        }
