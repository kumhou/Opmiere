"""Map Opmiere Project → OpenShot timeline plan (JSON-serializable).

Engine-independent plan is built on the host; the OpenShot worker only
consumes the plan (paths + seconds + layer + visual props).

Mapped for path-C frame grab (incremental):
  - position / start / end / layer
  - overlay transform (x, y, scale)
  - opacity effect → alpha
  - rotate effect → rotation degrees
  - speed ≠ 1 → time_remap (source ↔ timeline) + correct fallback seek
  - crop effect → left/right/top/bottom fractions (best-effort)
  - blur amount (Brightness/Blur effects when available)
  - color brightness → approximate alpha/brightness keyframe
  - fade in/out → alpha keyframe ramps (best-effort)
  - vignette strength (Mask/edge darken when available)
  - sharpen amount (Sharpen/Convolution when available)
  - ken_burns → scale + location keyframe ramps
  - white_balance temperature → Hue/Sat approximation

Still unsupported (listed in plan): transitions, complex grade FX
(curves/lut/text/…), audio effects, chroma/luma key, base-track position.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..bundle import Bundle
from ..model import Project

__all__ = [
    "build_openshot_plan",
    "plan_preview_size",
    "clip_visual_props",
    "path_c_effect_catalog",
]

# Effect types the OpenShot path-C adapter can approximate for still frames.
_MAPPED_VISUAL = frozenset({
    "opacity", "rotate", "crop", "blur", "color", "fade",
    "vignette", "sharpen", "ken_burns", "white_balance",
})
# Known effects we intentionally skip (not paintable on path-C yet).
_UNMAPPED_VISUAL = frozenset({
    "gain", "text", "chroma_key", "luma_key",
    "curves", "film_grain", "glow", "lut3d",
    "shape_mask", "subtitles", "compression", "noise_reduction",
    "audio_eq",
})

# Current plan schema version (floors only in tests — never pin exact equality).
ADAPTER_VERSION = 5


def path_c_effect_catalog() -> dict[str, Any]:
    """Agent/desktop catalog of what path-C can approximate vs skip."""
    return {
        "adapter_version": ADAPTER_VERSION,
        "mapped": sorted(_MAPPED_VISUAL),
        "unmapped": sorted(_UNMAPPED_VISUAL),
        "notes": {
            "vignette": "Mask or edge darken best-effort",
            "sharpen": "Sharpen effect when libopenshot exposes it",
            "ken_burns": "scale_x/y + location_x/y keyframe ramps",
            "white_balance": "temperature → hue/sat approximation",
            "color": "brightness only on still frames",
        },
    }


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


def clip_visual_props(
    clip: Any,
    *,
    project_w: int = 1920,
    project_h: int = 1080,
) -> dict[str, Any]:
    """Derive OpenShot-friendly visual props + per-effect support notes."""
    opacity = 1.0
    rotation = 0.0
    crop: dict[str, float] | None = None
    blur = 0.0
    brightness = 0.0
    fade_in = 0
    fade_out = 0
    vignette = 0.0
    sharpen = 0.0
    ken_burns: dict[str, float] | None = None
    white_balance: dict[str, float] | None = None
    mapped: list[str] = []
    unmapped: list[str] = []
    for e in clip.effects or []:
        if not isinstance(e, dict):
            continue
        et = e.get("type")
        if et == "opacity":
            try:
                opacity = float(e.get("amount", 1.0))
            except (TypeError, ValueError):
                opacity = 1.0
            opacity = max(0.0, min(1.0, opacity))
            mapped.append("opacity")
        elif et == "rotate":
            try:
                rotation = float(e.get("degrees", 0.0))
            except (TypeError, ValueError):
                rotation = 0.0
            mapped.append("rotate")
        elif et == "blur":
            try:
                blur = float(e.get("amount", 0) or 0)
            except (TypeError, ValueError):
                blur = 0.0
            if blur > 0:
                mapped.append("blur")
            else:
                unmapped.append("blur")
        elif et == "color":
            try:
                brightness = float(e.get("brightness", 0) or 0)
            except (TypeError, ValueError):
                brightness = 0.0
            # only brightness is approximated on path-C stills
            mapped.append("color")
        elif et == "fade":
            try:
                d = int(e.get("duration_frames") or 0)
            except (TypeError, ValueError):
                d = 0
            direction = e.get("direction")
            if direction == "in" and d > 0:
                fade_in = d
                mapped.append("fade")
            elif direction == "out" and d > 0:
                fade_out = d
                mapped.append("fade")
            else:
                unmapped.append("fade")
        elif et == "vignette":
            try:
                vignette = float(e.get("strength", 1.0) or 0)
            except (TypeError, ValueError):
                vignette = 0.0
            if vignette > 0:
                mapped.append("vignette")
            else:
                unmapped.append("vignette")
        elif et == "sharpen":
            try:
                sharpen = float(e.get("amount", 1.0) or 0)
            except (TypeError, ValueError):
                sharpen = 0.0
            if sharpen > 0:
                mapped.append("sharpen")
            else:
                unmapped.append("sharpen")
        elif et == "ken_burns":
            try:
                kb = {
                    "zoom_start": float(e.get("zoom_start", 1.0)),
                    "zoom_end": float(e.get("zoom_end", 1.2)),
                    "x_start": float(e.get("x_start", 0.5)),
                    "y_start": float(e.get("y_start", 0.5)),
                    "x_end": float(e.get("x_end", 0.5)),
                    "y_end": float(e.get("y_end", 0.5)),
                }
                ken_burns = kb
                mapped.append("ken_burns")
            except (TypeError, ValueError):
                unmapped.append("ken_burns")
        elif et == "white_balance":
            try:
                temp = float(e.get("temperature", 6500))
                mix = float(e.get("mix", 1.0))
                # Normalize Kelvin offset from daylight 6500 → roughly -1..1
                delta = max(-1.0, min(1.0, (temp - 6500.0) / 3500.0)) * max(0.0, min(1.0, mix))
                white_balance = {
                    "temperature": temp,
                    "mix": max(0.0, min(1.0, mix)),
                    "warmth": delta,
                }
                mapped.append("white_balance")
            except (TypeError, ValueError):
                unmapped.append("white_balance")
        elif et == "crop":
            # Opmiere crop is pixel box; convert to fractions of project frame.
            try:
                cw = float(e.get("width") or 0)
                ch = float(e.get("height") or 0)
                cx = e.get("x")
                cy = e.get("y")
                if isinstance(cx, str) and cx == "center":
                    x0 = max(0.0, (project_w - cw) / 2.0)
                else:
                    x0 = float(cx if isinstance(cx, (int, float)) else 0)
                if isinstance(cy, str) and cy == "center":
                    y0 = max(0.0, (project_h - ch) / 2.0)
                else:
                    y0 = float(cy if isinstance(cy, (int, float)) else 0)
                if cw > 0 and ch > 0 and project_w > 0 and project_h > 0:
                    left = max(0.0, min(1.0, x0 / project_w))
                    top = max(0.0, min(1.0, y0 / project_h))
                    right = max(0.0, min(1.0, 1.0 - (x0 + cw) / project_w))
                    bottom = max(0.0, min(1.0, 1.0 - (y0 + ch) / project_h))
                    crop = {
                        "left": left,
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                    }
                    mapped.append("crop")
                else:
                    unmapped.append("crop")
            except (TypeError, ValueError):
                unmapped.append("crop")
        elif et in _MAPPED_VISUAL:
            mapped.append(str(et))
        elif et:
            unmapped.append(str(et))
    return {
        "opacity": opacity,
        "rotation": rotation,
        "crop": crop,
        "blur": blur,
        "brightness": brightness,
        "fade_in_frames": fade_in,
        "fade_out_frames": fade_out,
        "vignette": vignette,
        "sharpen": sharpen,
        "ken_burns": ken_burns,
        "white_balance": white_balance,
        "mapped_effects": mapped,
        "unmapped_effects": unmapped,
    }


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
      - transform = overlay PiP (x/y top-left fraction, scale width fraction)
      - opacity / rotation / crop from mapped effects
      - speed ≠ 1 → time_remap + fallback source seek
    """
    fps = float(project.timebase.fps or 30.0)
    if fps <= 0:
        fps = 30.0
    w, h = plan_preview_size(project, height=height)
    proj_w = int(project.resolution.w or w)
    proj_h = int(project.resolution.h or h)
    tb = project.timebase

    unsupported: list[str] = []
    clips_out: list[dict[str, Any]] = []
    missing: list[str] = []
    mapped_notes: list[str] = []

    video_tracks = [
        tr for tr in project.tracks
        if tr.kind == "video" and not getattr(tr, "muted", False)
    ]
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
            speed = float(clip.speed or 1.0)
            if speed <= 0:
                speed = 1.0

            vis = clip_visual_props(clip, project_w=proj_w, project_h=proj_h)
            for ue in vis["unmapped_effects"]:
                unsupported.append(f"{ue}:{clip.id}")
            for me in vis["mapped_effects"]:
                mapped_notes.append(f"{me}:{clip.id}")

            entry: dict[str, Any] = {
                "id": clip.id,
                "path": str(path.resolve()),
                "position": pos_s,
                "start": src_in_s,
                "end": end_s,
                "layer": layer,
                "track_index": track_index,
                "speed": speed,
                "timeline_duration": timeline_dur_s,
                "source_duration": source_dur_s,
                "opacity": vis["opacity"],
                "rotation": vis["rotation"],
                "blur": vis.get("blur") or 0.0,
                "brightness": vis.get("brightness") or 0.0,
                "fade_in_frames": vis.get("fade_in_frames") or 0,
                "fade_out_frames": vis.get("fade_out_frames") or 0,
                "vignette": vis.get("vignette") or 0.0,
                "sharpen": vis.get("sharpen") or 0.0,
            }
            if vis.get("crop"):
                entry["crop"] = vis["crop"]
            if vis.get("ken_burns"):
                entry["ken_burns"] = vis["ken_burns"]
            if vis.get("white_balance"):
                entry["white_balance"] = vis["white_balance"]
            if abs(speed - 1.0) > 1e-3:
                # Constant speed: map timeline 0..timeline_dur → source start..end
                entry["time_remap"] = {
                    "enabled": True,
                    "source_start": src_in_s,
                    "source_end": end_s,
                    "timeline_duration": max(1e-6, timeline_dur_s),
                    "speed": speed,
                }
                mapped_notes.append(f"speed:{clip.id}")
            if clip.transition_in:
                unsupported.append(f"transition:{clip.id}")
            if clip.position and track_index > 0:
                entry["transform"] = {
                    "x": float(clip.position.get("x", 0.0)),
                    "y": float(clip.position.get("y", 0.0)),
                    "scale": float(clip.position.get("scale", 1.0)),
                }
                mapped_notes.append(f"transform:{clip.id}")
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

    # unique unsupported labels (kind only for summary)
    seen: set[str] = set()
    un_unique: list[str] = []
    for u in unsupported:
        kind = u.split(":")[0]
        if kind not in seen:
            seen.add(kind)
            un_unique.append(kind)

    mapped_kinds: list[str] = []
    seen_m: set[str] = set()
    for m in mapped_notes:
        kind = m.split(":")[0]
        if kind not in seen_m:
            seen_m.add(kind)
            mapped_kinds.append(kind)

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
        "mapped": mapped_kinds,
        "mapped_detail": mapped_notes[:40],
        "mode": "openshot_project_plan",
        "adapter_version": ADAPTER_VERSION,
        "effect_catalog": path_c_effect_catalog(),
    }
