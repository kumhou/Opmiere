"""Project-level look language + shot-to-shot color match helpers.

Professional assemblies share one grade language. These tools measure a
reference frame (ffmpeg signalstats) and emit ordinary effect dicts
(color / white_balance) so render stays on the existing filter path.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .probe import require_ffmpeg_tools

__all__ = [
    "LOOK_PRESETS",
    "measure_frame_stats",
    "suggest_color_match_effects",
    "resolve_look",
]

# Session looks — deterministic, free, agent-selectable when no_opinion
# or when brief asks for a coherent grade language.
LOOK_PRESETS: dict[str, list[dict[str, Any]]] = {
    "neutral": [],
    "cool_setup": [
        {"type": "white_balance", "temperature": 7800, "mix": 0.28},
        {"type": "color", "saturation": 0.95, "contrast": 1.04, "brightness": -0.02},
    ],
    "warm_resolve": [
        {"type": "white_balance", "temperature": 5200, "mix": 0.32},
        {"type": "color", "saturation": 1.06, "contrast": 1.05, "brightness": 0.01},
    ],
    "cinematic": [
        {"type": "curves", "preset": "increase_contrast"},
        {"type": "color", "saturation": 0.92, "contrast": 1.08, "brightness": -0.03},
        {"type": "vignette", "strength": 0.45},
    ],
    "vintage": [
        {"type": "curves", "preset": "vintage"},
        {"type": "color", "saturation": 0.88, "contrast": 1.02},
    ],
    "documentary": [
        {"type": "color", "saturation": 1.02, "contrast": 1.06, "brightness": 0.0},
        {"type": "sharpen", "amount": 0.6},
    ],
}


def resolve_look(
    look: str | list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Expand a look name or pass through an effect list."""
    if look is None or look == "" or look == "neutral":
        return []
    if isinstance(look, list):
        return [dict(e) for e in look]
    if look not in LOOK_PRESETS:
        raise ValueError(
            f"unknown look {look!r}; choose one of {sorted(LOOK_PRESETS)} "
            f"or pass a list of effect dicts"
        )
    return [dict(e) for e in LOOK_PRESETS[look]]


def measure_frame_stats(
    path: Path | str,
    time_seconds: float = 0.0,
) -> dict[str, Any]:
    """Sample one frame's signalstats (Y/U/V and R/G/B when available)."""
    require_ffmpeg_tools()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    t = max(0.0, float(time_seconds))
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner",
            "-ss", f"{t:.3f}",
            "-i", str(path),
            "-frames:v", "1",
            "-vf", "signalstats,metadata=print:file=-",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    text = (proc.stderr or "") + (proc.stdout or "")
    stats: dict[str, float] = {}
    # lavfi.signalstats.YAVG=123.4
    for m in re.finditer(
        r"(?:lavfi\.signalstats\.)?([A-Z]{2,12})=(-?[\d.]+)",
        text,
    ):
        key = m.group(1).lower()
        try:
            stats[key] = float(m.group(2))
        except ValueError:
            continue
    if "yavg" not in stats:
        raise RuntimeError(
            f"could not measure frame stats for {path} @ {t:.3f}s:\n{text[-1500:]}"
        )
    return {
        "path": str(path),
        "time_seconds": t,
        "yavg": stats.get("yavg"),
        "uavg": stats.get("uavg"),
        "vavg": stats.get("vavg"),
        "ravg": stats.get("ravg"),
        "gavg": stats.get("gavg"),
        "bavg": stats.get("bavg"),
        "raw": stats,
    }


def suggest_color_match_effects(
    reference: dict[str, Any],
    target: dict[str, Any],
    *,
    strength: float = 0.65,
) -> list[dict[str, Any]]:
    """Build ordinary effects that pull ``target`` toward ``reference`` look.

    strength in (0, 1] — 1 is aggressive match (can look artificial).
    """
    if not (0.0 < float(strength) <= 1.0):
        raise ValueError("strength must be in (0, 1]")
    s = float(strength)
    effects: list[dict[str, Any]] = []

    ry = float(reference.get("yavg") or 128.0)
    ty = float(target.get("yavg") or 128.0)
    # eq brightness is roughly -1..1; map 255 luma span → ~0.4 max shift
    bright = max(-0.25, min(0.25, (ry - ty) / 255.0 * s * 0.9))
    # mild contrast if target is flatter (lower... we only have mean; skip)

    # White-balance heuristic from R/B ratio when available
    rr, rb = reference.get("ravg"), reference.get("bavg")
    tr, tb = target.get("ravg"), target.get("bavg")
    temperature = None
    mix = None
    if None not in (rr, rb, tr, tb) and rb and tb:
        ref_rb = float(rr) / max(float(rb), 1.0)
        tgt_rb = float(tr) / max(float(tb), 1.0)
        # higher R/B → warmer; colortemperature lower Kelvin = warmer
        delta = (ref_rb - tgt_rb) * s
        # map small ratio delta to Kelvin shift around 6500
        temperature = int(round(6500 - delta * 1800))
        temperature = max(3200, min(10000, temperature))
        mix = round(min(0.55, 0.2 + abs(delta) * 0.5), 3)

    if abs(bright) >= 0.01 or True:
        effects.append({
            "type": "color",
            "brightness": round(bright, 4),
            "contrast": 1.0,
            "saturation": 1.0,
        })
    if temperature is not None and mix and mix >= 0.12 and abs(temperature - 6500) >= 150:
        effects.append({
            "type": "white_balance",
            "temperature": temperature,
            "mix": mix,
        })

    # UV-based tint: if reference more "warm" via V (in YUV V is red-ish)
    rv, tv = reference.get("vavg"), target.get("vavg")
    if rv is not None and tv is not None and temperature is None:
        # V channel: higher often redder in limited range ~128 center
        d_v = (float(rv) - float(tv)) * s
        if abs(d_v) > 3.0:
            temperature = int(round(6500 - d_v * 25))
            temperature = max(3200, min(10000, temperature))
            effects.append({
                "type": "white_balance",
                "temperature": temperature,
                "mix": round(min(0.45, 0.15 + abs(d_v) / 80.0), 3),
            })

    return effects
