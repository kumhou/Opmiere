"""Asset cards: professional-facing analysis of one media file.

Combines probe + scenes + silence keep_ranges + optional ASR + motion into a
single JSON-serializable card the agent uses for shot allocation / EDL.
Optional cache under a project bundle's analysis/ folder.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .motion import analyze_motion
from .probe import probe
from .scene_detect import detect_scenes
from .silence_edit import suggest_keep_ranges

__all__ = [
    "analyze_asset",
    "suggest_project_fps",
    "suggest_project_resolution",
    "check_delivery_limits",
    "plan_edit",
    "load_analysis_cache",
    "save_analysis_cache",
]

# Delivery ladders agents may request; max is clamped by source material.
_FPS_ALLOWED = (24.0, 25.0, 30.0, 50.0, 60.0)
_RES_PRESETS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
    "2160p": (3840, 2160),
}


def suggest_project_fps(
    paths: list[Path | str] | None = None,
    *,
    preference: str = "auto",
) -> dict[str, Any]:
    """Recommend timeline fps: 24 / 30 / 60 (and 25/50 when sources are PAL-like).

    preference: auto | 24 | 25 | 30 | 50 | 60
    - auto: majority vote from sources; true 50/60 material can unlock 60
    - explicit: honor if in allowed set; still report source max
    Low-fps AI drafts (<22) do not pull the project down.
    """
    allowed_pref = {"auto", "24", "25", "30", "50", "60"}
    if preference not in allowed_pref:
        raise ValueError(f"preference must be one of {sorted(allowed_pref)}")

    sources: list[dict[str, Any]] = []
    max_src = 0.0
    for p in paths or []:
        path = Path(p)
        if not path.exists():
            continue
        info = probe(path)
        if not info.has_video or not info.fps:
            continue
        fps = float(info.fps)
        max_src = max(max_src, fps)
        sources.append({"path": str(path), "fps": round(fps, 3)})

    warnings: list[str] = []
    if preference != "auto":
        want = float(preference)
        if max_src > 0 and want > max_src + 1.0:
            warnings.append(
                f"requested {want:g}fps exceeds highest source fps ({max_src:.2f}); "
                f"motion may look stepped or require frame interpolation (not free quality)"
            )
        return {
            "fps": want,
            "reason": f"user preference {preference}",
            "sources": sources,
            "source_max_fps": max_src or None,
            "warnings": warnings,
            "allowed": list(_FPS_ALLOWED),
        }

    votes = {"24": 0, "25": 0, "30": 0, "50": 0, "60": 0}
    for s in sources:
        fps = s["fps"]
        if 22.0 <= fps <= 24.5:
            votes["24"] += 1
        elif 24.5 < fps <= 26.5:
            votes["25"] += 1
        elif 28.0 <= fps <= 32.0:
            votes["30"] += 1
        elif 48.0 <= fps <= 52.0:
            votes["50"] += 1
        elif 55.0 <= fps <= 62.0:
            votes["60"] += 1
        elif fps < 22:
            pass
        else:
            votes["30"] += 1

    if not sources:
        return {
            "fps": 30.0,
            "reason": "no video sources — default 30",
            "sources": [],
            "source_max_fps": None,
            "warnings": [],
            "allowed": list(_FPS_ALLOWED),
        }

    # Prefer higher cadence when material supports it (60 > 30 > 24)
    order = ["60", "50", "30", "25", "24"]
    best = max(order, key=lambda k: (votes[k], order.index(k) * -0.01))
    if votes[best] == 0:
        best = "30"
    # If any 60-class source exists and ties/near, pick 60 for max fidelity
    if votes["60"] > 0 and votes["60"] >= votes["30"]:
        best = "60"
    elif votes["50"] > 0 and votes["50"] >= votes["25"] and votes["60"] == 0:
        best = "50"

    return {
        "fps": float(best),
        "reason": f"auto from sources (votes={votes})",
        "sources": sources,
        "source_max_fps": max_src,
        "warnings": warnings,
        "allowed": list(_FPS_ALLOWED),
    }


def suggest_project_resolution(
    paths: list[Path | str] | None = None,
    *,
    preference: str = "auto",
) -> dict[str, Any]:
    """Recommend timeline resolution; never invent pixels sources don't have.

    preference: auto | 720p | 1080p | 1440p | 4k
    - auto: largest ladder step not exceeding min(source widths/heights) ceiling
      using max source dimensions (export can letterbox weaker clips)
    - explicit: honor but **warn/block quality claim** if sources are smaller
    """
    sources: list[dict[str, Any]] = []
    max_w = max_h = 0
    min_w = min_h = 10**9
    for p in paths or []:
        path = Path(p)
        if not path.exists():
            continue
        info = probe(path)
        if not info.has_video or not info.width or not info.height:
            continue
        w, h = int(info.width), int(info.height)
        max_w, max_h = max(max_w, w), max(max_h, h)
        min_w, min_h = min(min_w, w), min(min_h, h)
        sources.append({"path": str(path), "width": w, "height": h})

    if min_w > 10**8:
        min_w = min_h = 0

    def _pick_auto() -> tuple[int, int, str]:
        if max_w >= 3800 and max_h >= 2100:
            return 3840, 2160, "4k — sources include UHD material"
        if max_w >= 2500 and max_h >= 1400:
            return 2560, 1440, "1440p — sources support QHD"
        if max_w >= 1800 and max_h >= 1000:
            return 1920, 1080, "1080p — sources support FHD"
        if max_w >= 1200 and max_h >= 700:
            return 1280, 720, "720p — limited source resolution"
        if max_w > 0:
            # odd sizes: use max source as canvas
            return max_w, max_h, "match largest source pixel size"
        return 1920, 1080, "no video sources — default 1080p (generate or import media first)"

    warnings: list[str] = []
    errors: list[str] = []
    if preference == "auto":
        w, h, reason = _pick_auto()
    elif preference in _RES_PRESETS:
        w, h = _RES_PRESETS[preference]
        reason = f"user preference {preference}"
        if max_w > 0 and (w > max_w + 8 or h > max_h + 8):
            msg = (
                f"requested {w}x{h} exceeds largest source {max_w}x{max_h}; "
                f"export would upscale — not true {preference} detail. "
                f"Lower target or supply higher-resolution footage."
            )
            warnings.append(msg)
            errors.append(msg)
    else:
        raise ValueError(
            f"preference must be auto or one of {sorted(_RES_PRESETS)}; got {preference!r}"
        )

    # Weaker clips in a 4k timeline
    if sources and max_w > 0 and min_w < w * 0.9:
        warnings.append(
            f"some sources are only {min_w}x{min_h} while project is {w}x{h}; "
            f"those clips will be upscaled/padded and look softer than true {w}x{h}"
        )

    return {
        "width": w,
        "height": h,
        "label": preference if preference != "auto" else (
            "4k" if w >= 3800 else "1440p" if w >= 2500 else "1080p" if w >= 1800 else "720p" if w >= 1200 else "custom"
        ),
        "reason": reason,
        "sources": sources,
        "source_max": {"width": max_w or None, "height": max_h or None},
        "source_min": {"width": min_w or None, "height": min_h or None},
        "warnings": warnings,
        "errors": errors,  # hard limits for agents — do not claim native 4k if errors non-empty
        "feasible_native": len(errors) == 0,
    }


def check_delivery_limits(
    *,
    paths: list[Path | str] | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Agent-facing gate: can this project honestly claim fps/resolution?

    Use before create_project / export. ``ok=False`` means the requested
    delivery exceeds source material — upscale or frame invent is not free
    quality; agent must warn the user and either lower the target or get
    higher-res/higher-fps footage.
    """
    fps_pref = "auto"
    if fps is not None:
        for cand in ("24", "25", "30", "50", "60"):
            if abs(float(fps) - float(cand)) < 0.6:
                fps_pref = cand
                break
    res_pref = "auto"
    if width and height:
        for label, (pw, ph) in _RES_PRESETS.items():
            if abs(width - pw) <= 16 and abs(height - ph) <= 16:
                res_pref = label if label != "2160p" else "4k"
                break

    fps_info = suggest_project_fps(paths, preference=fps_pref)
    res_info = suggest_project_resolution(
        paths, preference=res_pref if res_pref != "auto" else "auto"
    )
    # When custom WxH not matching a preset, still compare against sources
    if width and height and res_pref == "auto":
        res_info = suggest_project_resolution(paths, preference="auto")
        # synthetic explicit check
        max_w = (res_info.get("source_max") or {}).get("width") or 0
        max_h = (res_info.get("source_max") or {}).get("height") or 0
        if max_w and (width > max_w + 8 or height > max_h + 8):
            res_info = dict(res_info)
            msg = (
                f"requested {width}x{height} exceeds largest source "
                f"{max_w}x{max_h}; export would upscale — not true native detail."
            )
            res_info["warnings"] = list(res_info.get("warnings") or []) + [msg]
            res_info["errors"] = list(res_info.get("errors") or []) + [msg]
            res_info["feasible_native"] = False
            res_info["width"], res_info["height"] = width, height

    warnings: list[str] = []
    errors: list[str] = []
    if fps is not None and fps_info.get("source_max_fps"):
        if float(fps) > float(fps_info["source_max_fps"]) + 1.0:
            errors.append(
                f"timeline {fps:g}fps > source max {fps_info['source_max_fps']:.2f}fps "
                f"— motion may look stepped; not free quality from interpolation"
            )
    if width and height and res_info.get("source_max", {}).get("width"):
        sw, sh = res_info["source_max"]["width"], res_info["source_max"]["height"]
        if width > sw + 8 or height > sh + 8:
            errors.append(
                f"timeline {width}x{height} exceeds largest source {sw}x{sh} "
                f"— not native resolution; do not claim 4k/UHD quality"
            )
    for e in res_info.get("errors") or []:
        if e not in errors:
            errors.append(e)
    warnings.extend(fps_info.get("warnings") or [])
    for w in res_info.get("warnings") or []:
        if w not in warnings and w not in errors:
            warnings.append(w)
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "suggest_fps": fps_info,
        "suggest_resolution": res_info,
        "agent_note": (
            "If ok=false: lower fps/resolution to source-feasible values, or ask "
            "user for higher-quality material. Never present upscaled export as "
            "native 4k / 60fps."
        ),
    }


# Map motion affinity strings → KNOWN_TRANSITION_TYPES (or None = hard cut).
_AFFINITY_TO_TRANSITION = {
    "hard_cut": None,
    "cross_dissolve": "cross_dissolve",
    "wipe_left": "wipe_left",
    "wipe_right": "wipe_right",
    "wipe_up": "wipe_up",
    "wipe_down": "wipe_down",
    "dip_to_black": "dip_to_black",
    "dip_to_white": "dip_to_white",
}


def _seconds_to_src_frames(seconds: float, project_fps: float) -> int:
    """Project-timebase frames (same convention as Media.duration_frames)."""
    return max(0, int(round(float(seconds) * float(project_fps))))


def _media_kind_from_card(card: dict[str, Any]) -> str:
    if card.get("has_video"):
        return "video"
    if card.get("has_audio"):
        return "audio"
    return "image"


def _segments_from_card(
    card: dict[str, Any],
    *,
    cut_silence: bool,
    prefer_scenes: bool,
    max_clip_seconds: float | None,
) -> list[dict[str, Any]]:
    """Pick source ranges for one asset: keep_ranges → scenes → whole file."""
    duration = float(card.get("duration_seconds") or 0.0)
    if duration <= 0:
        return []

    segs: list[dict[str, Any]] = []
    silence = card.get("silence") if isinstance(card.get("silence"), dict) else None
    scenes = card.get("scenes") if isinstance(card.get("scenes"), dict) else None

    if cut_silence and silence and not silence.get("error"):
        keeps = silence.get("keep_ranges") or []
        if keeps and (
            len(keeps) > 1
            or (keeps[0].get("duration") or 0) < duration * 0.95
        ):
            for k in keeps:
                segs.append({
                    "start": float(k["start"]),
                    "end": float(k["end"]),
                    "reason": "silence_keep",
                })

    if not segs and prefer_scenes and scenes and not scenes.get("error"):
        scene_list = scenes.get("scenes") or []
        if len(scene_list) >= 2:
            for s in scene_list:
                segs.append({
                    "start": float(s.get("start") if s.get("start") is not None else s.get("start_time", 0)),
                    "end": float(s.get("end") if s.get("end") is not None else s.get("end_time", duration)),
                    "reason": "scene",
                })

    if not segs:
        segs = [{"start": 0.0, "end": duration, "reason": "whole"}]

    # Cap very long single segments when requested
    if max_clip_seconds and max_clip_seconds > 0:
        capped: list[dict[str, Any]] = []
        for s in segs:
            t0, t1 = s["start"], s["end"]
            while t1 - t0 > max_clip_seconds + 0.05:
                capped.append({
                    "start": t0,
                    "end": t0 + max_clip_seconds,
                    "reason": s["reason"] + "+cap",
                })
                t0 += max_clip_seconds
            if t1 - t0 >= 0.05:
                capped.append({"start": t0, "end": t1, "reason": s["reason"]})
        segs = capped

    # Drop empty / inverted
    return [s for s in segs if s["end"] - s["start"] >= 0.05]


def _pick_transition(
    prev_card: dict[str, Any] | None,
    next_card: dict[str, Any],
    *,
    transition_default: str,
) -> str | None:
    """Return transition type name or None for hard cut."""
    if transition_default != "auto":
        if transition_default in ("none", "hard_cut", "cut"):
            return None
        return _AFFINITY_TO_TRANSITION.get(transition_default, transition_default)

    ta_next = next_card.get("transition_affinity") or {}
    preferred_in = ta_next.get("preferred_transition_in") or "hard_cut"
    if prev_card:
        ta_prev = prev_card.get("transition_affinity") or {}
        preferred_out = ta_prev.get("preferred_transition_out") or "hard_cut"
        # Prefer agreement; else next clip's preferred_in
        if preferred_out == preferred_in:
            return _AFFINITY_TO_TRANSITION.get(preferred_in)
        if preferred_out != "hard_cut" and preferred_in == "hard_cut":
            return _AFFINITY_TO_TRANSITION.get(preferred_out)
        return _AFFINITY_TO_TRANSITION.get(preferred_in)
    return _AFFINITY_TO_TRANSITION.get(preferred_in)


def plan_edit(
    cards: list[dict[str, Any]] | None = None,
    paths: list[Path | str] | None = None,
    *,
    fps: float = 30.0,
    width: int | None = None,
    height: int | None = None,
    cut_silence: bool = True,
    prefer_scenes: bool = True,
    max_clip_seconds: float | None = None,
    transition_default: str = "auto",
    transition_frames: int = 12,
    analyze_if_needed: bool = True,
) -> dict[str, Any]:
    """Build an EDL-like edit plan from asset cards (or paths).

    Does **not** mutate a project. Agent (or ``Editor.apply_edit_plan``) applies
    the events. Ordering: a_roll/vo on base tracks, then b_roll/still as
    sequential base shots if no a_roll else listed as overlay candidates,
    music/sfx on audio.

    Each event:
      op, path, kind, role, track_hint, src_in_seconds, src_out_seconds,
      src_in_frames, src_out_frames, transition_in, note
    """
    if transition_frames < 0:
        raise ValueError("transition_frames must be >= 0")

    built: list[dict[str, Any]] = list(cards or [])
    if not built and paths:
        for p in paths:
            path = Path(p)
            if not path.exists():
                continue
            if analyze_if_needed:
                built.append(
                    analyze_asset(
                        path,
                        do_scenes=prefer_scenes,
                        do_silence=cut_silence,
                        do_motion=True,
                        do_transcribe=False,
                    )
                )
            else:
                info = probe(path)
                built.append({
                    "path": str(path.resolve()),
                    "duration_seconds": info.duration_seconds,
                    "fps": info.fps,
                    "width": info.width,
                    "height": info.height,
                    "has_video": info.has_video,
                    "has_audio": info.has_audio,
                    "role_guess": "b_roll" if info.has_video else ("music" if info.has_audio else "other"),
                    "transition_affinity": _transition_affinity({}),
                })

    source_paths = [c.get("path") for c in built if c.get("path")]
    delivery = check_delivery_limits(
        paths=source_paths,
        fps=fps,
        width=width,
        height=height,
    )

    # Bucket by role
    buckets: dict[str, list[dict[str, Any]]] = {
        "a_roll": [], "b_roll": [], "vo": [], "music": [], "sfx": [],
        "still": [], "other": [],
    }
    for c in built:
        role = str(c.get("role_guess") or c.get("role") or "other")
        if role not in buckets:
            role = "other"
        buckets[role].append(c)

    events: list[dict[str, Any]] = []
    warnings: list[str] = list(delivery.get("warnings") or [])
    warnings.extend(delivery.get("errors") or [])  # surface hard limits in plan warnings too

    def _emit_video_sequence(card_list: list[dict[str, Any]], track_hint: str) -> None:
        prev_card: dict[str, Any] | None = None
        for card in card_list:
            segs = _segments_from_card(
                card,
                cut_silence=cut_silence,
                prefer_scenes=prefer_scenes,
                max_clip_seconds=max_clip_seconds,
            )
            kind = _media_kind_from_card(card)
            role = str(card.get("role_guess") or card.get("role") or "other")
            for i, seg in enumerate(segs):
                t_in = None
                t_type = None
                if events and track_hint.startswith("video"):
                    # only transition between video base events
                    last = events[-1]
                    if last.get("track_hint") == track_hint and last.get("kind") == "video":
                        t_type = _pick_transition(
                            prev_card if i == 0 else card,
                            card,
                            transition_default=transition_default,
                        )
                        if t_type and transition_frames > 0:
                            t_in = {
                                "type": t_type,
                                "duration_frames": int(transition_frames),
                            }
                src_in_f = _seconds_to_src_frames(seg["start"], fps)
                src_out_f = _seconds_to_src_frames(seg["end"], fps)
                if src_out_f <= src_in_f:
                    src_out_f = src_in_f + max(1, int(round(0.1 * fps)))
                events.append({
                    "op": "place",
                    "path": card.get("path"),
                    "kind": kind,
                    "role": role,
                    "track_hint": track_hint,
                    "src_in_seconds": round(seg["start"], 3),
                    "src_out_seconds": round(seg["end"], 3),
                    "src_in_frames": src_in_f,
                    "src_out_frames": src_out_f,
                    "transition_in": t_in,
                    "note": f"segment via {seg['reason']}",
                })
            prev_card = card

    # Primary picture: a_roll first, else b_roll/still as base sequence
    base_video = buckets["a_roll"] or buckets["b_roll"] or buckets["still"]
    if buckets["a_roll"] and buckets["b_roll"]:
        _emit_video_sequence(buckets["a_roll"], "video_base")
        # B-roll: sequential after A-roll on base for simple auto-cut;
        # agent can re-layer as overlay later
        _emit_video_sequence(buckets["b_roll"], "video_base")
        warnings.append(
            "b_roll placed on video_base after a_roll (simple auto EDL); "
            "agent may move selected shots to video_overlay for cutaways"
        )
    else:
        _emit_video_sequence(base_video, "video_base")

    if not buckets["a_roll"] and buckets["still"] and buckets["b_roll"]:
        pass  # already handled via base_video = b_roll
    elif buckets["still"] and buckets["a_roll"]:
        _emit_video_sequence(buckets["still"], "video_base")

    # Audio beds
    for card in buckets["vo"]:
        segs = _segments_from_card(
            card, cut_silence=cut_silence, prefer_scenes=False, max_clip_seconds=None,
        )
        for seg in segs:
            events.append({
                "op": "place",
                "path": card.get("path"),
                "kind": _media_kind_from_card(card),
                "role": "vo",
                "track_hint": "audio_vo",
                "src_in_seconds": round(seg["start"], 3),
                "src_out_seconds": round(seg["end"], 3),
                "src_in_frames": _seconds_to_src_frames(seg["start"], fps),
                "src_out_frames": _seconds_to_src_frames(seg["end"], fps),
                "transition_in": None,
                "note": f"vo via {seg['reason']}",
            })
    for card in buckets["music"]:
        dur = float(card.get("duration_seconds") or 0)
        events.append({
            "op": "place",
            "path": card.get("path"),
            "kind": "audio",
            "role": "music",
            "track_hint": "audio_music",
            "src_in_seconds": 0.0,
            "src_out_seconds": round(dur, 3),
            "src_in_frames": 0,
            "src_out_frames": _seconds_to_src_frames(dur, fps),
            "transition_in": None,
            "note": "music bed full file",
        })
    for card in buckets["sfx"]:
        dur = float(card.get("duration_seconds") or 0)
        events.append({
            "op": "place",
            "path": card.get("path"),
            "kind": "audio",
            "role": "sfx",
            "track_hint": "audio_sfx",
            "src_in_seconds": 0.0,
            "src_out_seconds": round(dur, 3),
            "src_in_frames": 0,
            "src_out_frames": _seconds_to_src_frames(dur, fps),
            "transition_in": None,
            "note": "sfx full file",
        })
    for card in buckets["other"]:
        warnings.append(f"unclassified asset skipped in auto EDL: {card.get('path')}")

    total_tl = 0
    for e in events:
        if e.get("track_hint") == "video_base":
            total_tl += max(0, e["src_out_frames"] - e["src_in_frames"])
            if e.get("transition_in"):
                total_tl -= int(e["transition_in"]["duration_frames"])

    return {
        "version": 1,
        "fps": float(fps),
        "width": width,
        "height": height,
        "delivery": delivery,
        "events": events,
        "event_count": len(events),
        "approx_video_base_frames": max(0, total_tl),
        "warnings": warnings,
        "roles": {k: len(v) for k, v in buckets.items() if v},
        "agent_note": (
            "Review events before apply_edit_plan. delivery.ok=false means "
            "requested fps/resolution exceeds sources — warn user, do not claim "
            "native 4k/60fps. Adjust transitions/order if auto affinity is wrong."
        ),
    }


def _guess_role(card: dict[str, Any]) -> str:
    if not card.get("has_video") and card.get("has_audio"):
        # speech-like if we got transcript text
        segs = (card.get("speech") or {}).get("segments") or []
        if segs:
            return "vo"
        return "music" if (card.get("duration_seconds") or 0) > 20 else "sfx"
    if card.get("has_video"):
        speech = card.get("speech") or {}
        segs = speech.get("segments") or []
        text_len = sum(len(s.get("text") or "") for s in segs)
        motion = (card.get("motion") or {}).get("label")
        if text_len > 12:
            return "a_roll"
        if motion in ("static",) and (card.get("duration_seconds") or 0) < 4:
            return "still"
        return "b_roll"
    return "other"


def _transition_affinity(motion: dict[str, Any]) -> dict[str, Any]:
    """How this clip likes to be joined, from entry/exit + motion labels."""
    entry = motion.get("entry") or "cut_in"
    exit_ = motion.get("exit") or "cut_out"
    label = motion.get("label") or "static"
    preferred_in = "cross_dissolve" if entry == "fade_in" else (
        "wipe_right" if label == "pan_left" else (
            "wipe_left" if label == "pan_right" else "hard_cut"
        )
    )
    preferred_out = "cross_dissolve" if exit_ == "fade_out" else (
        "wipe_left" if label == "pan_left" else (
            "wipe_right" if label == "pan_right" else (
                "hard_cut" if exit_ != "motion_out" else "cross_dissolve"
            )
        )
    )
    return {
        "entry": entry,
        "exit": exit_,
        "preferred_transition_in": preferred_in,
        "preferred_transition_out": preferred_out,
        "motion_label": label,
        "notes": (
            "Motion/fade heuristics only — agent should verify on contact sheet."
        ),
    }


def analyze_asset(
    path: Path | str,
    *,
    do_scenes: bool = True,
    do_silence: bool = True,
    do_motion: bool = True,
    do_transcribe: bool = False,
    scene_backend: str = "auto",
    transcribe_language: str | None = None,
    model_size: str = "base",
) -> dict[str, Any]:
    """Build a full asset card for one file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = probe(path)
    card: dict[str, Any] = {
        "path": str(path.resolve()),
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": info.duration_seconds,
        "fps": info.fps,
        "width": info.width,
        "height": info.height,
        "has_video": info.has_video,
        "has_audio": info.has_audio,
    }

    if do_scenes and info.has_video:
        try:
            card["scenes"] = detect_scenes(path, backend=scene_backend)
        except Exception as e:
            card["scenes"] = {"error": str(e)}
    else:
        card["scenes"] = None

    if do_silence and info.has_audio:
        try:
            card["silence"] = suggest_keep_ranges(path)
        except Exception as e:
            card["silence"] = {"error": str(e)}
    else:
        card["silence"] = None

    if do_motion and info.has_video:
        try:
            card["motion"] = analyze_motion(path)
        except Exception as e:
            card["motion"] = {"error": str(e), "label": "unknown"}
    else:
        card["motion"] = {"has_video": False, "label": "none"}

    if do_transcribe and info.has_audio:
        try:
            from .asr import transcribe
            card["speech"] = transcribe(
                path, language=transcribe_language, model_size=model_size,
                word_timestamps=True,
            )
        except Exception as e:
            card["speech"] = {"error": str(e)}
    else:
        card["speech"] = None

    motion = card.get("motion") if isinstance(card.get("motion"), dict) else {}
    card["transition_affinity"] = _transition_affinity(motion)
    card["role_guess"] = _guess_role(card)
    card["suggested_uses"] = _suggested_uses(card)
    return card


def _suggested_uses(card: dict[str, Any]) -> list[str]:
    uses: list[str] = []
    role = card.get("role_guess")
    if role:
        uses.append(f"role:{role}")
    ta = card.get("transition_affinity") or {}
    if ta.get("exit") == "motion_out":
        uses.append("good_transition_out")
    if ta.get("entry") == "fade_in":
        uses.append("soft_open")
    sil = card.get("silence") or {}
    if isinstance(sil, dict) and len(sil.get("silences") or []) >= 2:
        uses.append("cut_dead_air")
    scenes = card.get("scenes") or {}
    if isinstance(scenes, dict) and (scenes.get("scene_count") or 0) >= 3:
        uses.append("split_into_scenes")
    motion = card.get("motion") or {}
    if motion.get("label") in ("pan_left", "pan_right", "push_in"):
        uses.append("pair_with_matching_motion")
    return uses


def analysis_cache_path(bundle_root: Path, media_path: str | Path) -> Path:
    key = Path(media_path).name.replace(" ", "_")
    return Path(bundle_root) / "analysis" / f"{key}.json"


def save_analysis_cache(bundle_root: Path, card: dict[str, Any]) -> Path:
    p = analysis_cache_path(bundle_root, card.get("path") or "asset")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_analysis_cache(bundle_root: Path, media_path: str | Path) -> dict[str, Any] | None:
    p = analysis_cache_path(bundle_root, media_path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
