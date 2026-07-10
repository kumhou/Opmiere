"""Named cut templates — productized first-cut recipes for common formats.

Not a black-box auto-editor: each template is an ordered, inspectable plan of
real Editor tools (place_batch, style, duck, optional filler/silence hints).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CUT_TEMPLATES",
    "list_templates",
    "get_template",
]

CUT_TEMPLATES: dict[str, dict[str, Any]] = {
    "talking_head": {
        "label": "Talking head / 口播",
        "description": (
            "A-roll talking footage + optional music bed. "
            "Documentary grade, hard cuts, music ducks under VO/speech track."
        ),
        "style": "documentary",
        "roles": {
            "a_roll": "video talking head / screen recording",
            "music": "optional bed",
            "vo": "optional separate VO wav",
        },
        "options": {
            "sequential_video": True,
            "duck_music_under_vo": True,
            "suggest_silence": True,
            "suggest_filler": True,
            "normalize_preset": "streaming",
        },
        "next_steps": [
            "suggest_silence_cuts / apply_keep_ranges on A-roll if dead air",
            "suggest_filler_cuts dry_run then apply if um/那个 dense",
            "transcribe_media + caption_clip if captions needed",
            "review_cut → export(normalize_preset=streaming) → delivery_check",
        ],
    },
    "short_form": {
        "label": "Short-form / 短视频",
        "description": (
            "Punchy vertical-ish social cut: sequential A-roll, thriller pace grade, "
            "optional music. Prefer short holds; agent may speed or trim further."
        ),
        "style": "thriller",
        "roles": {
            "a_roll": "hook clips in delivery order",
            "music": "optional bed",
        },
        "options": {
            "sequential_video": True,
            "duck_music_under_vo": False,
            "suggest_silence": True,
            "suggest_filler": False,
            "normalize_preset": "streaming",
            "music_gain_db": -10,
        },
        "next_steps": [
            "Tighten with ripple_trim / edge_trim on weak opens",
            "apply_style_preset cyberpunk or thriller+wes_anderson if brand needs pop",
            "export_range for 15–60s variants",
            "delivery_check",
        ],
    },
    "interview": {
        "label": "Interview / 双机位对话",
        "description": (
            "Multiple A-roll clips sequential (A/B cameras as separate files), "
            "optional music low, documentary look. Agent handles L/J with detach_audio."
        ),
        "style": "documentary",
        "roles": {
            "a_roll": "camera A then B files in cut order",
            "music": "optional sparse bed",
            "vo": "optional",
        },
        "options": {
            "sequential_video": True,
            "duck_music_under_vo": True,
            "suggest_silence": True,
            "suggest_filler": True,
            "normalize_preset": "streaming",
            "music_gain_db": -16,
        },
        "next_steps": [
            "detach_audio on reaction shots for L-cuts",
            "color_match_to_clip(hero) across cameras",
            "room_tone under dialogue gaps",
            "review_cut → export → delivery_check",
        ],
    },
    "vlog": {
        "label": "Vlog day-in-the-life",
        "description": (
            "Mixed A-roll + optional stills/B-roll paths, mild cinematic grade, "
            "music bed under speech when present."
        ),
        "style": "cinematic",
        "roles": {
            "a_roll": "phone/camera clips in story order",
            "music": "optional",
        },
        "options": {
            "sequential_video": True,
            "duck_music_under_vo": True,
            "suggest_silence": False,
            "suggest_filler": False,
            "normalize_preset": "streaming",
            "image_duration_frames": 75,
        },
        "next_steps": [
            "plan_edit for B-roll overlay if extra paths",
            "apply_style_preset ang_lee for calmer days",
            "export + delivery_check",
        ],
    },
}


def list_templates() -> dict[str, Any]:
    return {
        "names": sorted(CUT_TEMPLATES),
        "templates": {
            k: {
                "label": v.get("label"),
                "description": v.get("description"),
                "style": v.get("style"),
                "roles": v.get("roles"),
            }
            for k, v in CUT_TEMPLATES.items()
        },
    }


def get_template(name: str) -> dict[str, Any]:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "talkinghead": "talking_head",
        "口播": "talking_head",
        "short": "short_form",
        "shorts": "short_form",
        "短视频": "short_form",
        "访谈": "interview",
    }
    key = aliases.get(key, key)
    if key not in CUT_TEMPLATES:
        raise ValueError(
            f"unknown cut template {name!r}; choose from {sorted(CUT_TEMPLATES)}"
        )
    import copy
    out = copy.deepcopy(CUT_TEMPLATES[key])
    out["id"] = key
    return out
