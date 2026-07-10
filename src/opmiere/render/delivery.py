"""Delivery finish: loudness normalize + honest export acceptance gate.

Professional exports fail more often on *levels and claimed specs* than on
missing filters. This module:
- normalizes integrated loudness (ffmpeg loudnorm) to platform targets
- checks a finished file against fps/resolution/duration/LUFS/true-peak
  and the free quality_check dead-clip gates

Agent rule: do not present an export as final until delivery_check ok=true
(or the user explicitly accepts warnings).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .audio_critic import analyze_audio
from .probe import probe, require_ffmpeg_tools
from .quality_check import quality_check

__all__ = [
    "LOUDNESS_PRESETS",
    "normalize_loudness",
    "delivery_check",
]

# I = integrated LUFS, TP = true peak dBTP, LRA = loudness range LU
LOUDNESS_PRESETS: dict[str, dict[str, float]] = {
    "streaming": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
    "youtube": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
    "bilibili": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
    "douyin": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
    "podcast": {"I": -16.0, "TP": -1.5, "LRA": 11.0},
    "broadcast": {"I": -23.0, "TP": -1.0, "LRA": 18.0},
}

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def _resolve_targets(
    preset: str | None,
    *,
    target_lufs: float | None = None,
    true_peak: float | None = None,
    lra: float | None = None,
) -> dict[str, float]:
    if preset is not None:
        if preset not in LOUDNESS_PRESETS:
            raise ValueError(
                f"unknown loudness preset {preset!r}; "
                f"choose one of {sorted(LOUDNESS_PRESETS)}"
            )
        base = dict(LOUDNESS_PRESETS[preset])
    else:
        base = dict(LOUDNESS_PRESETS["streaming"])
    if target_lufs is not None:
        base["I"] = float(target_lufs)
    if true_peak is not None:
        base["TP"] = float(true_peak)
    if lra is not None:
        base["LRA"] = float(lra)
    return base


def _measure_loudnorm(path: Path, targets: dict[str, float]) -> dict[str, Any]:
    """First loudnorm pass — print measured_* for linear second pass."""
    af = (
        f"loudnorm=I={targets['I']}:TP={targets['TP']}:LRA={targets['LRA']}:"
        f"print_format=json"
    )
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", af, "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    # loudnorm JSON is on stderr
    text = proc.stderr or ""
    m = _JSON_BLOCK.search(text)
    if not m:
        # fallback: last {...} blob
        start = text.rfind("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            blob = text[start : end + 1]
        else:
            raise RuntimeError(
                f"loudnorm measure failed (exit {proc.returncode}); no JSON:\n{text[-2000:]}"
            )
    else:
        blob = m.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"loudnorm measure JSON parse failed: {e}\n{blob}") from e
    return data


def normalize_loudness(
    path: Path | str,
    output_path: Path | str,
    *,
    preset: str = "streaming",
    target_lufs: float | None = None,
    true_peak: float | None = None,
    lra: float | None = None,
    two_pass: bool = True,
) -> dict[str, Any]:
    """Write a loudness-normalized copy of ``path`` to ``output_path``.

    Video streams are stream-copied when present; audio is re-encoded AAC.
    Audio-only inputs keep a reasonable codec (aac in .m4a/.mp4, else pcm_s16le
    for .wav). Returns before/after meters + the filter settings used.
    """
    require_ffmpeg_tools()
    path = Path(path)
    output_path = Path(output_path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = probe(path)
    if not info.has_audio:
        raise ValueError(f"{path} has no audio stream to normalize")

    targets = _resolve_targets(
        preset, target_lufs=target_lufs, true_peak=true_peak, lra=lra,
    )
    before = analyze_audio(path)

    if two_pass:
        measured = _measure_loudnorm(path, targets)
        # measured keys from ffmpeg loudnorm print_format=json
        def _m(key: str, default: str = "0") -> str:
            v = measured.get(key, default)
            return str(v)

        af = (
            f"loudnorm=I={targets['I']}:TP={targets['TP']}:LRA={targets['LRA']}:"
            f"measured_I={_m('input_i')}:"
            f"measured_LRA={_m('input_lra')}:"
            f"measured_TP={_m('input_tp')}:"
            f"measured_thresh={_m('input_thresh')}:"
            f"offset={_m('target_offset', '0')}:"
            f"linear=true:print_format=summary"
        )
    else:
        measured = None
        af = (
            f"loudnorm=I={targets['I']}:TP={targets['TP']}:LRA={targets['LRA']}:"
            f"print_format=summary"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(path), "-af", af]
    if info.has_video:
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    else:
        suf = output_path.suffix.lower()
        if suf in (".wav",):
            cmd += ["-c:a", "pcm_s16le"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(output_path))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(
            f"loudnorm encode failed (exit {proc.returncode}):\n{proc.stderr[-3000:]}"
        )

    after = analyze_audio(output_path)
    return {
        "path": str(output_path),
        "preset": preset,
        "targets": targets,
        "two_pass": two_pass,
        "measured_first_pass": measured,
        "before": {
            "integrated_lufs": before.get("integrated_lufs"),
            "true_peak_dbfs": before.get("true_peak_dbfs"),
            "loudness_range_lu": before.get("loudness_range_lu"),
            "mean_volume_db": before.get("mean_volume_db"),
        },
        "after": {
            "integrated_lufs": after.get("integrated_lufs"),
            "true_peak_dbfs": after.get("true_peak_dbfs"),
            "loudness_range_lu": after.get("loudness_range_lu"),
            "mean_volume_db": after.get("mean_volume_db"),
        },
        "agent_note": (
            "Re-run delivery_check on the normalized path before calling the cut final."
        ),
    }


def delivery_check(
    path: Path | str,
    *,
    preset: str = "streaming",
    target_lufs: float | None = None,
    true_peak_limit: float | None = None,
    lufs_tolerance: float = 1.5,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
    expected_duration_seconds: float | None = None,
    duration_tolerance_seconds: float = 0.35,
    run_quality_check: bool = True,
) -> dict[str, Any]:
    """Honest gate on a finished export (or any media file).

    ok=false means do not claim professional delivery without fixing or
    getting an explicit user waiver. Combines probe, loudness meters, and
    optional quality_check (black/frozen/blurry/silent).
    """
    require_ffmpeg_tools()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    targets = _resolve_targets(
        preset,
        target_lufs=target_lufs,
        true_peak=true_peak_limit,
    )
    # true peak limit: use TP from targets unless overridden
    tp_limit = float(
        true_peak_limit if true_peak_limit is not None else targets["TP"]
    )
    target_i = float(targets["I"])

    info = probe(path)
    errors: list[str] = []
    warnings: list[str] = []

    # --- video geometry / timing ---
    if expected_width is not None and info.width is not None:
        if abs(int(info.width) - int(expected_width)) > 8:
            errors.append(
                f"width {info.width} != expected {expected_width}"
            )
    if expected_height is not None and info.height is not None:
        if abs(int(info.height) - int(expected_height)) > 8:
            errors.append(
                f"height {info.height} != expected {expected_height}"
            )
    if expected_fps is not None and info.fps:
        if abs(float(info.fps) - float(expected_fps)) > 0.6:
            errors.append(
                f"fps {info.fps:.3f} != expected {expected_fps:g}"
            )
    if expected_duration_seconds is not None:
        delta = abs(float(info.duration_seconds) - float(expected_duration_seconds))
        if delta > duration_tolerance_seconds:
            errors.append(
                f"duration {info.duration_seconds:.2f}s differs from expected "
                f"{expected_duration_seconds:.2f}s by {delta:.2f}s"
            )

    # --- audio loudness ---
    audio_report: dict[str, Any] | None = None
    if info.has_audio:
        audio_report = analyze_audio(path)
        lufs = audio_report.get("integrated_lufs")
        peak = audio_report.get("true_peak_dbfs")
        mean_db = audio_report.get("mean_volume_db")
        if lufs is not None:
            if abs(float(lufs) - target_i) > lufs_tolerance:
                errors.append(
                    f"integrated loudness {lufs:.1f} LUFS outside "
                    f"{target_i:g}±{lufs_tolerance:g} (preset {preset}); "
                    f"run normalize_loudness"
                )
        else:
            warnings.append("could not measure integrated LUFS")
        if peak is not None and float(peak) > tp_limit + 0.05:
            errors.append(
                f"true peak {peak:.2f} dBFS exceeds limit {tp_limit:g} "
                f"(risk of clipping after platform re-encode)"
            )
        if mean_db is not None and float(mean_db) < -45.0:
            warnings.append(
                f"mean volume {mean_db:.1f} dB is very low — mix may sound empty"
            )
        if mean_db is not None and float(mean_db) > -6.0:
            warnings.append(
                f"mean volume {mean_db:.1f} dB is very hot — check for distortion"
            )
        # long leading/trailing silence
        silences = audio_report.get("silences") or []
        dur = float(info.duration_seconds)
        for s in silences:
            if s.get("start_seconds", 1) <= 0.05 and s.get("duration_seconds", 0) >= 0.8:
                warnings.append(
                    f"leading silence ~{s['duration_seconds']:.1f}s — trim head?"
                )
            if s.get("end_seconds", 0) >= dur - 0.05 and s.get("duration_seconds", 0) >= 0.8:
                warnings.append(
                    f"trailing silence ~{s['duration_seconds']:.1f}s — trim tail?"
                )
    else:
        warnings.append("no audio stream — delivery is picture-only")

    # --- free quality gate ---
    qc: dict[str, Any] | None = None
    if run_quality_check and (info.has_video or info.has_audio):
        try:
            qc = quality_check(path).to_dict()
            if not qc.get("passed"):
                for issue in qc.get("issues") or []:
                    errors.append(f"quality_check: {issue}")
        except Exception as e:
            warnings.append(f"quality_check skipped: {e}")

    ok = len(errors) == 0
    return {
        "ok": ok,
        "path": str(path.resolve()),
        "preset": preset,
        "targets": {"I": target_i, "TP": tp_limit, "LRA": targets.get("LRA")},
        "probe": {
            "duration_seconds": info.duration_seconds,
            "fps": info.fps,
            "width": info.width,
            "height": info.height,
            "has_video": info.has_video,
            "has_audio": info.has_audio,
        },
        "audio": audio_report,
        "quality_check": qc,
        "errors": errors,
        "warnings": warnings,
        "agent_note": (
            "If ok=false: fix levels with normalize_loudness, re-export, or lower "
            "claimed specs — do not call this a finished professional delivery."
            if not ok
            else "Delivery gate passed for the checked criteria."
        ),
    }
