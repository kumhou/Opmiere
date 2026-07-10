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
    "load_analysis_cache",
    "save_analysis_cache",
]


def suggest_project_fps(
    paths: list[Path | str] | None = None,
    *,
    preference: str = "auto",
) -> dict[str, Any]:
    """Recommend timeline fps for professional look without generation burden.

    preference: auto | 24 | 30
    - auto: if primary video near 24/25 → 24; near 30/29.97/60 → 30; else 30
    - 24 / 30: honor explicitly
    Generation models may still use lower fps for drafts; the *timeline*
    should stay 24/30 for viewing quality when user material allows.
    """
    if preference in ("24", "30"):
        return {
            "fps": float(preference),
            "reason": f"user preference {preference}",
            "sources": [],
        }
    sources: list[dict[str, Any]] = []
    votes_24 = votes_30 = 0
    for p in paths or []:
        path = Path(p)
        if not path.exists():
            continue
        info = probe(path)
        if not info.has_video or not info.fps:
            continue
        fps = float(info.fps)
        sources.append({"path": str(path), "fps": fps})
        if 22.0 <= fps <= 26.0:
            votes_24 += 1
        elif 28.0 <= fps <= 32.0 or 55.0 <= fps <= 62.0:
            votes_30 += 1
        elif fps < 22:
            # generated low-fps stock — don't drag the whole project down
            pass
        else:
            votes_30 += 1
    if votes_24 > votes_30:
        return {"fps": 24.0, "reason": "majority of sources near 24fps film cadence", "sources": sources}
    if votes_30 > 0 or sources:
        return {"fps": 30.0, "reason": "majority of sources near 30/60 or default social cadence", "sources": sources}
    return {"fps": 30.0, "reason": "no video sources — default 30 for general delivery", "sources": []}


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
