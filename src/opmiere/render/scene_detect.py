"""Shot/scene boundary detection on user footage.

Primary: PySceneDetect (ContentDetector). Optional dependency
``scenedetect[opencv]``. Falls back to ffmpeg's scene score filter when
PySceneDetect is not installed so the MCP surface still works offline.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["detect_scenes", "SceneDetectNotInstalledError"]


class SceneDetectNotInstalledError(RuntimeError):
    pass


def _via_scenedetect(path: Path, threshold: float, min_scene_len: int) -> list[dict[str, Any]]:
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(str(path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    sm.detect_scenes(video)
    scene_list = sm.get_scene_list()
    scenes: list[dict[str, Any]] = []
    for i, (start, end) in enumerate(scene_list):
        # scenedetect 0.6+ prefers .seconds / .frame_num (0 is a valid value —
        # do not use `or` fallback which would call deprecated getters).
        def _sec(tc) -> float:
            if hasattr(tc, "seconds"):
                return float(tc.seconds)
            return float(tc.get_seconds())

        def _fr(tc) -> int:
            if hasattr(tc, "frame_num"):
                return int(tc.frame_num)
            return int(tc.get_frames())

        start_s, end_s = _sec(start), _sec(end)
        start_f, end_f = _fr(start), _fr(end)
        scenes.append({
            "index": i,
            "start": round(start_s, 3),
            "end": round(end_s, 3),
            "duration": round(end_s - start_s, 3),
            "start_frame": start_f,
            "end_frame": end_f,
        })
    return scenes


def _via_ffmpeg(path: Path, threshold: float) -> list[dict[str, Any]]:
    """Fallback: ffmpeg select scene score. threshold ~0.2–0.5 typical."""
    require_ffmpeg_tools()
    # showinfo prints pts_time at scene cuts when select=gt(scene,T)
    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(path),
            "-filter:v", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    info = probe(path)
    duration = float(info.duration_seconds)
    fps = float(info.fps or 30.0)
    cuts = [0.0]
    for m in re.finditer(r"pts_time:([\d.]+)", proc.stderr):
        t = float(m.group(1))
        if t > cuts[-1] + 0.05:
            cuts.append(t)
    if cuts[-1] < duration - 0.05:
        cuts.append(duration)
    elif abs(cuts[-1] - duration) > 0.05:
        cuts.append(duration)
    scenes: list[dict[str, Any]] = []
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        scenes.append({
            "index": i,
            "start": round(s, 3),
            "end": round(e, 3),
            "duration": round(e - s, 3),
            "start_frame": int(round(s * fps)),
            "end_frame": int(round(e * fps)),
        })
    if not scenes:
        scenes = [{
            "index": 0,
            "start": 0.0,
            "end": round(duration, 3),
            "duration": round(duration, 3),
            "start_frame": 0,
            "end_frame": int(round(duration * fps)),
        }]
    return scenes


def detect_scenes(
    path: Path | str,
    *,
    threshold: float = 27.0,
    min_scene_len: int = 15,
    backend: str = "auto",
) -> dict[str, Any]:
    """Detect scene boundaries in a video file.

    ``backend``: ``auto`` (PySceneDetect if available else ffmpeg),
    ``scenedetect``, or ``ffmpeg``.

    PySceneDetect ContentDetector threshold is typically 27–30 (higher =
    fewer cuts). FFmpeg backend uses a 0–1 scene score (default mapped from
    threshold/100 when threshold > 1).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = probe(path)
    if not info.has_video:
        raise ValueError(f"{path} has no video stream")

    used = backend
    scenes: list[dict[str, Any]]
    if backend == "ffmpeg":
        t = threshold if threshold <= 1.0 else threshold / 100.0
        scenes = _via_ffmpeg(path, t)
        used = "ffmpeg"
    elif backend == "scenedetect":
        try:
            scenes = _via_scenedetect(path, threshold, min_scene_len)
            used = "scenedetect"
        except ImportError as e:
            raise SceneDetectNotInstalledError(
                "PySceneDetect not installed. pip install 'scenedetect[opencv]' "
                "or use backend='ffmpeg'"
            ) from e
    else:  # auto
        try:
            scenes = _via_scenedetect(path, threshold, min_scene_len)
            used = "scenedetect"
        except ImportError:
            t = threshold if threshold <= 1.0 else min(0.5, threshold / 100.0)
            scenes = _via_ffmpeg(path, t)
            used = "ffmpeg"

    return {
        "path": str(path),
        "backend": used,
        "threshold": threshold,
        "duration_seconds": info.duration_seconds,
        "fps": info.fps,
        "scene_count": len(scenes),
        "scenes": scenes,
    }
