"""Map Opmiere Project → OpenShot timeline plan (JSON-serializable).

Engine-independent plan is built on the host; the OpenShot worker only
consumes the plan (paths + seconds + layer). Effects / transitions /
full speed curves are tracked as unsupported for incremental mapping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..bundle import Bundle
from ..model import Project

__all__ = ["build_openshot_plan", "plan_preview_size"]


def plan_preview_size(
    project: Project,
    *,
    height: int = 360,
) -> tuple[int, int]:
    # libopenshot Timeline on Windows AV-crashes at very small sizes (e.g. 212x120
    # failed; 320x180 ok). Keep even dims and a safe minimum canvas.
    h = max(180, int(height) // 2 * 2)
    aspect = project.resolution.w / max(project.resolution.h, 1)
    w = max(320, int(round(h * aspect)) // 2 * 2)
    return w, h

def build_openshot_plan(
    project: Project,
    bundle: Bundle,
    *,
    height: int = 360,
    include_audio: bool = False,
) -> dict[str, Any]:
    """Compile video (and optional audio) clips into an OpenShot plan.

    OpenShot mapping:
      - Position  = timeline start (seconds)
      - Start/End = source trim (seconds, media fps ≈ project fps for conformed assets)
      - Layer     = track order (base track low; overlays higher = on top)
    """
    fps = float(project.timebase.fps or 30.0)
    if fps <= 0:
        fps = 30.0
    w, h = plan_preview_size(project, height=height)
    tb = project.timebase

    unsupported: list[str] = []
    clips_out: list[dict[str, Any]] = []
    missing: list[str] = []

    video_tracks = [tr for tr in project.tracks if tr.kind == "video" and not getattr(tr, "muted", False)]
    # Solo handling: if any video track is soloed, only those
    soloed = [tr for tr in video_tracks if getattr(tr, "solo", False)]
    if soloed:
        video_tracks = soloed

    for track_index, track in enumerate(video_tracks):
        # OpenShot: higher layer draws on top; base = 1, overlays 2+
        layer = track_index + 1
        for clip in track.clips_in_order():
            if clip.muted:
                continue
            media = project.media_by_id(clip.media)
            path = Path(bundle.media_path(media.path))
            if not path.exists():
                missing.append(str(path))
                continue
            # Prefer media proxy for speed when present
            if media.proxy_path:
                proxy_abs = bundle.resolve_bundle_path(media.proxy_path)
                if proxy_abs.exists():
                    path = proxy_abs

            src_in_s = tb.frames_to_seconds(clip.src_in)
            src_out_s = tb.frames_to_seconds(clip.src_out)
            pos_s = tb.frames_to_seconds(clip.start)
            timeline_dur_s = tb.frames_to_seconds(clip.timeline_duration_frames)
            source_dur_s = max(1e-6, src_out_s - src_in_s)
            # libopenshot GetFrame AV-crashes if End sits on exact media EOF on some
            # Windows builds — pull end in a half-frame.
            end_s = max(src_in_s + 1.0 / fps, src_out_s - (0.5 / fps))

            entry: dict[str, Any] = {
                "id": clip.id,
                "path": str(path.resolve()),
                "position": pos_s,
                "start": src_in_s,
                "end": end_s,
                "layer": layer,
                "track_index": track_index,
                "speed": float(clip.speed or 1.0),
                "timeline_duration": timeline_dur_s,
                "source_duration": source_dur_s,
            }
            if abs(float(clip.speed or 1.0) - 1.0) > 1e-3:
                unsupported.append(f"speed:{clip.id}")
            if clip.effects:
                unsupported.append(f"effects:{clip.id}")
            if clip.transition_in:
                unsupported.append(f"transition:{clip.id}")
            if clip.position and track_index > 0:
                # overlay transform
                entry["transform"] = {
                    "x": float(clip.position.get("x", 0.0)),
                    "y": float(clip.position.get("y", 0.0)),
                    "scale": float(clip.position.get("scale", 1.0)),
                }
            elif clip.position and track_index == 0:
                unsupported.append(f"base_position_ignored:{clip.id}")
            clips_out.append(entry)

    if include_audio:
        # deferred: audio mix in interactive preview is optional for frame grab
        pass

    duration_frames = 0
    for track in project.tracks:
        for c in track.clips:
            duration_frames = max(duration_frames, c.end)
    duration_s = tb.frames_to_seconds(duration_frames)

    # unique unsupported labels
    seen: set[str] = set()
    un_unique: list[str] = []
    for u in unsupported:
        kind = u.split(":")[0]
        if kind not in seen:
            seen.add(kind)
            un_unique.append(kind)

    return {
        "width": w,
        "height": h,
        "fps": fps,
        # OpenShot preview timeline: stereo @ 44100 is the well-tested path
        "sample_rate": 44100,
        "duration_seconds": duration_s,
        "duration_frames": duration_frames,
        "clips": clips_out,
        "clip_count": len(clips_out),
        "missing_media": missing,
        "unsupported": un_unique,
        "unsupported_detail": unsupported[:40],
        "mode": "openshot_project_plan",
    }
