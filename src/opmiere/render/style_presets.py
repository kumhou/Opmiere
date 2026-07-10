"""Film aesthetic style library — parameters, not generation.

Agent retrieves/blends these presets then applies deterministic effects.
Matches the 'style as technical constants' design: pacing hints + grade +
transition preferences. No invented LUT paths unless the file exists.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

__all__ = [
    "STYLE_PRESETS",
    "list_styles",
    "get_style",
    "blend_styles",
    "resolve_style_effects",
    "style_asset_search_dirs",
    "resolve_style_asset",
    "list_style_assets",
]

# Hand-tuned constants (edit like a colorist, not a prompt). Agents mix names.
STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "ang_lee": {
        "label": "Ang Lee–inspired restraint",
        "min_clip_seconds": 3.5,
        "max_clip_seconds": None,
        "transition_preference": "cross_dissolve",
        "transition_frames": 20,
        "pace": "unhurried",
        "framing_rule": "center_balanced",
        "camera_movement": "slow_zoom",
        "look": "cinematic",
        "effects": [
            {"type": "color", "saturation": 0.94, "contrast": 1.04, "brightness": -0.02},
            {"type": "white_balance", "temperature": 5800, "mix": 0.2},
            {"type": "vignette", "strength": 0.25},
        ],
        "audio": {"music_gain_db": -10, "prefer_duck": True},
        "notes": "Longer holds, slow dissolves, mild contrast, neutral-warm.",
    },
    "horror": {
        "label": "Horror atmosphere",
        "min_clip_seconds": 0.4,
        "max_clip_seconds": 8.0,
        "transition_preference": "hard_cut",
        "transition_frames": 0,
        "pace": "dread_then_cut",
        "framing_rule": "unbalanced_edge",
        "camera_movement": "static_or_creep",
        "look": None,
        # Optional local assets (applied only if file exists):
        "color_lut": "cold_terror.cube",
        "audio_track_layer": "low_drone.wav",
        "effects": [
            {"type": "white_balance", "temperature": 8200, "mix": 0.45},
            {"type": "color", "saturation": 0.75, "contrast": 1.18, "brightness": -0.08},
            {"type": "curves", "preset": "darker"},
            {"type": "vignette", "strength": 1.2},
        ],
        "audio": {"music_gain_db": -6, "prefer_duck": False},
        "notes": "Cold grade, heavy vignette, hard cuts; optional LUT/drone if present under assets/.",
    },
    "wes_anderson": {
        "label": "Wes Anderson–inspired symmetry pop",
        "min_clip_seconds": 1.5,
        "transition_preference": "hard_cut",
        "transition_frames": 0,
        "pace": "tableaus",
        "framing_rule": "center_symmetry",
        "look": None,
        "effects": [
            {"type": "color", "saturation": 1.15, "contrast": 1.06, "brightness": 0.02},
            {"type": "white_balance", "temperature": 5400, "mix": 0.25},
            {"type": "vignette", "strength": 0.15},
        ],
        "audio": {"music_gain_db": -8, "prefer_duck": True},
        "notes": "Punchy pastel grade, center-framed stills; hard cuts.",
    },
    "cyberpunk": {
        "label": "Cyberpunk night neon",
        "min_clip_seconds": 0.8,
        "transition_preference": "cross_dissolve",
        "transition_frames": 8,
        "pace": "pulse",
        "look": None,
        "effects": [
            {"type": "white_balance", "temperature": 9000, "mix": 0.35},
            {"type": "color", "saturation": 1.2, "contrast": 1.15, "brightness": -0.05},
            {"type": "glow", "amount": 8.0, "intensity": 0.35},
            {"type": "vignette", "strength": 0.6},
        ],
        "audio": {"music_gain_db": -7, "prefer_duck": True},
        "notes": "Cool shadows, neon pop, light glow; short dissolves.",
    },
    "thriller": {
        "label": "Thriller tension",
        "min_clip_seconds": 1.0,
        "transition_preference": "cross_dissolve",
        "transition_frames": 6,
        "pace": "tightening",
        "look": None,
        "effects": [
            {"type": "color", "saturation": 0.85, "contrast": 1.12, "brightness": -0.04},
            {"type": "curves", "preset": "increase_contrast"},
            {"type": "vignette", "strength": 0.55},
        ],
        "audio": {"music_gain_db": -9, "prefer_duck": True},
        "notes": "Desaturated contrast, medium vignette.",
    },
    "documentary": {
        "label": "Observational documentary",
        "min_clip_seconds": 2.0,
        "transition_preference": "hard_cut",
        "transition_frames": 0,
        "pace": "observational",
        "look": "documentary",
        "effects": [
            {"type": "color", "saturation": 1.02, "contrast": 1.05, "brightness": 0.0},
            {"type": "sharpen", "amount": 0.5},
        ],
        "audio": {"music_gain_db": -14, "prefer_duck": True},
        "notes": "Clean grade, hard cuts, music bed under VO.",
    },
}


def list_styles() -> dict[str, Any]:
    return {
        "names": sorted(STYLE_PRESETS),
        "styles": {
            k: {
                "label": v.get("label"),
                "pace": v.get("pace"),
                "transition_preference": v.get("transition_preference"),
                "notes": v.get("notes"),
            }
            for k, v in STYLE_PRESETS.items()
        },
    }


def get_style(name: str) -> dict[str, Any]:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "lee": "ang_lee",
        "anglee": "ang_lee",
        "wes": "wes_anderson",
        "anderson": "wes_anderson",
        "doc": "documentary",
        "cyber": "cyberpunk",
        "cinematic": "ang_lee",
        "cinema": "ang_lee",
    }
    key = aliases.get(key, key)
    if key not in STYLE_PRESETS:
        raise ValueError(
            f"unknown style {name!r}; choose from {sorted(STYLE_PRESETS)}"
        )
    return copy.deepcopy(STYLE_PRESETS[key])


def blend_styles(names: list[str]) -> dict[str, Any]:
    """Merge 1–N styles: later names override scalar prefs; effects concatenate."""
    if not names:
        raise ValueError("names must be non-empty")
    base = get_style(names[0])
    merged_effects: list[dict[str, Any]] = list(base.get("effects") or [])
    looks: list[str] = []
    if base.get("look"):
        looks.append(str(base["look"]))
    for name in names[1:]:
        s = get_style(name)
        for k, v in s.items():
            if k == "effects":
                merged_effects.extend(copy.deepcopy(v or []))
            elif k == "look" and v:
                looks.append(str(v))
            elif k == "notes":
                base["notes"] = (base.get("notes") or "") + " | " + str(v)
            elif k == "audio" and isinstance(v, dict):
                audio = dict(base.get("audio") or {})
                audio.update(v)
                base["audio"] = audio
            else:
                base[k] = copy.deepcopy(v)
        # pacing: take min of min_clip, max of max when both set
        if "min_clip_seconds" in s and "min_clip_seconds" in base:
            try:
                base["min_clip_seconds"] = min(
                    float(base["min_clip_seconds"]), float(s["min_clip_seconds"])
                )
            except (TypeError, ValueError):
                pass
    base["effects"] = merged_effects
    base["blend"] = list(names)
    base["looks"] = looks
    return base


def resolve_style_effects(style: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten look name + explicit effects into apply_effect payloads."""
    from .look import resolve_look

    out: list[dict[str, Any]] = []
    for look_name in style.get("looks") or (
        [style["look"]] if style.get("look") else []
    ):
        out.extend(resolve_look(look_name))
    for fx in style.get("effects") or []:
        out.append(dict(fx))
    return out


def style_asset_search_dirs(bundle_root: Path | None = None) -> list[Path]:
    """Ordered dirs for LUT (.cube) and drone audio assets.

    Layout (any of these)::

        $OPMIERE_STYLE_ASSETS/
          luts/*.cube
          audio/*.wav
        <package>/assets/luts|audio
        <repo>/assets/luts|audio
        <cwd>/assets/luts|audio
        <bundle>/assets/luts|audio
    """
    import os

    dirs: list[Path] = []
    env = os.environ.get("OPMIERE_STYLE_ASSETS", "").strip()
    if env:
        dirs.append(Path(env))
    pkg = Path(__file__).resolve().parent.parent  # opmiere/
    dirs.append(pkg / "assets")
    # repo root when editable install: opmiere/src/opmiere/render → parents[3]
    dirs.append(Path(__file__).resolve().parents[3] / "assets")
    dirs.append(Path.cwd() / "assets")
    if bundle_root is not None:
        dirs.append(Path(bundle_root) / "assets")
    # unique preserve order
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def resolve_style_asset(
    name: str,
    *,
    kind: str = "lut",
    bundle_root: Path | None = None,
) -> Path | None:
    """Find a named style asset on disk, or None if missing.

    kind: ``lut`` → luts/ subdir + .cube; ``audio`` → audio/ + as given.
    Absolute paths that exist are returned as-is.
    """
    path = Path(name)
    if path.is_absolute() and path.exists():
        return path
    sub = "luts" if kind == "lut" else "audio"
    candidates: list[Path] = []
    for root in style_asset_search_dirs(bundle_root):
        candidates.append(root / sub / name)
        candidates.append(root / name)
    candidates.append(Path.cwd() / name)
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def list_style_assets(bundle_root: Path | None = None) -> dict[str, Any]:
    """Inventory available LUT/audio files under search dirs (for agents)."""
    luts: list[str] = []
    audio: list[str] = []
    roots: list[str] = []
    for root in style_asset_search_dirs(bundle_root):
        roots.append(str(root))
        lut_dir = root / "luts"
        if lut_dir.is_dir():
            for p in sorted(lut_dir.glob("*.cube")):
                luts.append(str(p))
        aud_dir = root / "audio"
        if aud_dir.is_dir():
            for p in sorted(aud_dir.iterdir()):
                if p.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac"}:
                    audio.append(str(p))
    return {
        "search_dirs": roots,
        "luts": luts,
        "audio": audio,
        "agent_note": (
            "Place .cube under assets/luts and beds under assets/audio "
            "(or OPMIERE_STYLE_ASSETS). Missing files are skipped, never invented."
        ),
    }
