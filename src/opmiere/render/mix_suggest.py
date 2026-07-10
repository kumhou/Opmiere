"""Suggest dialogue/music mix levels from real meters (not guesswork).

Returns actionable gain dB and set_ducking params an agent (or apply_mix_plan)
can execute. Targets approximate streaming dialogue clarity: VO near -16 LUFS
bed, music bed ~8–12 LU quieter when unducked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .audio_critic import analyze_audio

__all__ = ["suggest_mix", "suggest_dialogue_chain"]

# Target integrated loudness for stems before master normalize
_VO_TARGET_LUFS = -16.0
_MUSIC_ALONE_LUFS = -22.0  # sits under VO when not ducked hard
_MUSIC_WITH_VO_GAP = 8.0   # want music mean ~8 LU below VO when both present


def _lufs_or_mean(report: dict[str, Any]) -> float | None:
    lufs = report.get("integrated_lufs")
    if lufs is not None:
        return float(lufs)
    mean = report.get("mean_volume_db")
    if mean is not None:
        # rough: mean sample dB is not LUFS; shift conservatively
        return float(mean) + 3.0
    return None


def suggest_dialogue_chain(
    path: Path | str,
    *,
    has_music_bleed: bool = False,
) -> dict[str, Any]:
    """Recommended processing order for a dialogue/VO file."""
    path = Path(path)
    report = analyze_audio(path)
    level = _lufs_or_mean(report)
    steps: list[dict[str, Any]] = []
    if has_music_bleed:
        steps.append({
            "tool": "separate_stems",
            "purpose": "Isolate vocals from music bleed (Demucs)",
            "params": {"two_stems": "vocals"},
        })
    steps.append({
        "tool": "apply_effect",
        "effect": {"type": "noise_reduction"},
        "purpose": "Light denoise on dialogue (arnndn when available)",
        "optional": True,
    })
    steps.append({
        "tool": "apply_effect",
        "effect": {
            "type": "compression",
            "threshold_db": -24.0,
            "ratio": 3.0,
            "attack_ms": 10.0,
            "release_ms": 120.0,
        },
        "purpose": "Even out spoken level",
    })
    gain_db = 0.0
    if level is not None:
        gain_db = round(_VO_TARGET_LUFS - level, 1)
        gain_db = max(-12.0, min(12.0, gain_db))
    if abs(gain_db) >= 0.5:
        steps.append({
            "tool": "apply_effect",
            "effect": {"type": "gain", "db": gain_db},
            "purpose": f"Aim VO near {_VO_TARGET_LUFS:g} LUFS (measured {level})",
        })
    return {
        "path": str(path),
        "meters": {
            "integrated_lufs": report.get("integrated_lufs"),
            "mean_volume_db": report.get("mean_volume_db"),
            "true_peak_dbfs": report.get("true_peak_dbfs"),
        },
        "suggested_gain_db": gain_db,
        "target_lufs": _VO_TARGET_LUFS,
        "steps": steps,
        "agent_note": (
            "Apply on the VO clip after place. Then set_ducking(music, vo). "
            "Final master still uses normalize_loudness on export."
        ),
    }


def suggest_mix(
    *,
    vo_path: Path | str | None = None,
    music_path: Path | str | None = None,
    sfx_path: Path | str | None = None,
    vo_track_id: str | None = None,
    music_track_id: str | None = None,
    target_vo_lufs: float = _VO_TARGET_LUFS,
    target_music_lufs: float = _MUSIC_ALONE_LUFS,
) -> dict[str, Any]:
    """Suggest gain dB + ducking params from VO/music (and optional SFX) files.

    Paths are preferred for honest per-stem meters. Track ids are returned in
    the action list when provided so the agent can apply without re-lookup.
    """
    actions: list[dict[str, Any]] = []
    warnings: list[str] = []
    stems: dict[str, Any] = {}

    vo_level = music_level = sfx_level = None
    if vo_path:
        p = Path(vo_path)
        if not p.exists():
            raise FileNotFoundError(p)
        rep = analyze_audio(p)
        vo_level = _lufs_or_mean(rep)
        stems["vo"] = {
            "path": str(p),
            "integrated_lufs": rep.get("integrated_lufs"),
            "mean_volume_db": rep.get("mean_volume_db"),
            "true_peak_dbfs": rep.get("true_peak_dbfs"),
            "level": vo_level,
        }
    if music_path:
        p = Path(music_path)
        if not p.exists():
            raise FileNotFoundError(p)
        rep = analyze_audio(p)
        music_level = _lufs_or_mean(rep)
        stems["music"] = {
            "path": str(p),
            "integrated_lufs": rep.get("integrated_lufs"),
            "mean_volume_db": rep.get("mean_volume_db"),
            "true_peak_dbfs": rep.get("true_peak_dbfs"),
            "level": music_level,
        }
    if sfx_path:
        p = Path(sfx_path)
        if not p.exists():
            raise FileNotFoundError(p)
        rep = analyze_audio(p)
        sfx_level = _lufs_or_mean(rep)
        stems["sfx"] = {
            "path": str(p),
            "level": sfx_level,
            "integrated_lufs": rep.get("integrated_lufs"),
        }

    if not stems:
        raise ValueError("suggest_mix needs at least vo_path or music_path")

    vo_gain = 0.0
    if vo_level is not None:
        vo_gain = max(-12.0, min(12.0, round(target_vo_lufs - vo_level, 1)))
        if abs(vo_gain) >= 0.5:
            actions.append({
                "op": "gain",
                "role": "vo",
                "track_id": vo_track_id,
                "db": vo_gain,
                "reason": f"VO {vo_level:.1f} → ~{target_vo_lufs:g} LUFS",
            })

    music_gain = 0.0
    if music_level is not None:
        # Alone target, then ensure gap under VO if both known
        music_gain = target_music_lufs - music_level
        if vo_level is not None:
            # after vo_gain, effective VO ≈ target_vo
            want_music = target_vo_lufs - _MUSIC_WITH_VO_GAP
            music_gain = want_music - music_level
        music_gain = max(-18.0, min(6.0, round(music_gain, 1)))
        if abs(music_gain) >= 0.5:
            actions.append({
                "op": "gain",
                "role": "music",
                "track_id": music_track_id,
                "db": music_gain,
                "reason": (
                    f"music {music_level:.1f} → bed under VO "
                    f"(~{target_vo_lufs - _MUSIC_WITH_VO_GAP:g} LUFS)"
                    if vo_level is not None
                    else f"music {music_level:.1f} → ~{target_music_lufs:g} LUFS"
                ),
            })

    if sfx_level is not None and vo_level is not None:
        # SFX slightly under VO
        sfx_gain = max(-12.0, min(6.0, round((target_vo_lufs - 3.0) - sfx_level, 1)))
        if abs(sfx_gain) >= 0.5:
            actions.append({
                "op": "gain",
                "role": "sfx",
                "db": sfx_gain,
                "reason": "SFX a few LU under VO",
            })

    if vo_path and music_path:
        # Duck music under VO
        threshold = -30.0
        if vo_level is not None:
            # threshold a bit below VO average so speech keys ducking
            threshold = round(min(-20.0, vo_level - 8.0), 1)
        actions.append({
            "op": "set_ducking",
            "music_track_id": music_track_id,
            "vo_track_id": vo_track_id,
            "threshold_db": threshold,
            "ratio": 8.0,
            "attack_ms": 20.0,
            "release_ms": 280.0,
            "makeup_db": 0.0,
            "reason": "music yields when VO present",
        })
    elif music_path and not vo_path:
        warnings.append("music only — no ducking suggested; add VO path for dialogue bed")
    elif vo_path and not music_path:
        warnings.append("VO only — gain toward target; no ducking")

    return {
        "stems": stems,
        "actions": actions,
        "warnings": warnings,
        "targets": {
            "vo_lufs": target_vo_lufs,
            "music_lufs": target_music_lufs,
            "music_gap_under_vo_lu": _MUSIC_WITH_VO_GAP,
        },
        "agent_note": (
            "Apply gains on clips (apply_effect gain) per role; "
            "set_ducking(music_track, vo_track). Then analyze_timeline. "
            "Master loudness still via export normalize_preset / normalize_loudness."
        ),
    }
