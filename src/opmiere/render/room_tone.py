"""Room-tone / ambience fill for dead air after silence cuts.

Professional dialogue edits rarely leave digital black silence — they loop a
quiet bed from the same take. This module finds a usable donor segment and
can extract a short loopable WAV for the agent to place under cuts.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools
from .silence_edit import suggest_keep_ranges

__all__ = ["suggest_room_tone", "extract_room_tone"]


def suggest_room_tone(
    path: Path | str,
    *,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.35,
    min_donor_seconds: float = 0.25,
    max_donor_seconds: float = 2.5,
    prefer_mid: bool = True,
) -> dict[str, Any]:
    """Pick a quiet donor range from the same file for ambience loops.

    Prefers a mid-file silence pad (or shortest keep-gap) that is long enough
    to loop without an obvious button. Returns seconds ranges + guidance.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = probe(path)
    if not info.has_audio:
        raise ValueError(f"{path} has no audio — cannot derive room tone")

    sil = suggest_keep_ranges(
        path,
        silence_threshold_db=silence_threshold_db,
        min_silence_seconds=min_silence_seconds,
        pad_seconds=0.0,
        min_keep_seconds=0.05,
    )
    silences = list(sil.get("silences") or [])
    duration = float(info.duration_seconds)

    candidates: list[dict[str, Any]] = []
    for s in silences:
        d = float(s.get("duration") or 0)
        if d < min_donor_seconds:
            continue
        start = float(s["start"])
        end = float(s["end"])
        # trim donor to max length from center of silence
        if d > max_donor_seconds:
            mid = (start + end) / 2.0
            start = max(0.0, mid - max_donor_seconds / 2.0)
            end = min(duration, start + max_donor_seconds)
            start = max(0.0, end - max_donor_seconds)
        candidates.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "source": "silence",
        })

    if not candidates:
        # Fallback: last 0.4s of file (often handle/tail) or first 0.4s
        tail = min(max_donor_seconds, max(min_donor_seconds, duration * 0.1))
        if duration >= min_donor_seconds:
            if prefer_mid and duration > 1.0:
                mid = duration / 2.0
                start = max(0.0, mid - tail / 2.0)
                end = min(duration, start + tail)
            else:
                start = max(0.0, duration - tail)
                end = duration
            candidates.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "source": "fallback_segment",
            })

    if not candidates:
        return {
            "path": str(path.resolve()),
            "ok": False,
            "donor": None,
            "silences": silences,
            "agent_note": "No usable quiet segment — record room tone or skip fill.",
        }

    # Prefer mid-timeline silence, then longest
    def _score(c: dict[str, Any]) -> tuple:
        mid = (c["start"] + c["end"]) / 2.0
        center_bias = -abs(mid - duration / 2.0) if prefer_mid else 0.0
        return (c["duration"], center_bias)

    donor = max(candidates, key=_score)
    return {
        "path": str(path.resolve()),
        "ok": True,
        "duration_seconds": duration,
        "donor": donor,
        "candidates": candidates[:8],
        "silence_count": len(silences),
        "agent_note": (
            "Extract with extract_room_tone, place on an audio overlay under "
            "dialogue cuts, gain down ~-6 to -12 dB. Loop if gap longer than donor."
        ),
    }


def extract_room_tone(
    path: Path | str,
    output_path: Path | str,
    *,
    start: float | None = None,
    end: float | None = None,
    donor: dict[str, Any] | None = None,
    loop_to_seconds: float | None = None,
) -> dict[str, Any]:
    """Write a WAV (or m4a) room-tone clip from donor range; optional loop.

    If start/end omitted, runs suggest_room_tone and uses its donor.
    """
    require_ffmpeg_tools()
    path = Path(path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if donor is None and (start is None or end is None):
        sug = suggest_room_tone(path)
        if not sug.get("ok") or not sug.get("donor"):
            raise ValueError(sug.get("agent_note") or "no room tone donor")
        donor = sug["donor"]
    if donor is not None:
        start = float(donor["start"])
        end = float(donor["end"])
    assert start is not None and end is not None
    if end <= start:
        raise ValueError(f"invalid donor range {start}–{end}")

    dur = end - start
    # Extract segment
    tmp = output_path.with_suffix(".seg.wav")
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(path),
            "-vn", "-ac", "2", "-ar", "48000",
            str(tmp),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not tmp.exists():
        raise RuntimeError(
            f"extract room tone failed:\n{(proc.stderr or '')[-1500:]}"
        )

    final = output_path
    if loop_to_seconds is not None and loop_to_seconds > dur + 0.05:
        # aloop + atrim
        n = int(loop_to_seconds / dur) + 1
        proc2 = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner",
                "-stream_loop", str(max(0, n - 1)),
                "-i", str(tmp),
                "-t", f"{loop_to_seconds:.3f}",
                "-ac", "2", "-ar", "48000",
                str(final),
            ],
            capture_output=True, text=True,
        )
        if proc2.returncode != 0 or not final.exists():
            raise RuntimeError(
                f"loop room tone failed:\n{(proc2.stderr or '')[-1500:]}"
            )
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        out_dur = loop_to_seconds
    else:
        if final.suffix.lower() != tmp.suffix.lower():
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(tmp), str(final)],
                capture_output=True, text=True, check=True,
            )
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            tmp.replace(final)
        out_dur = dur

    return {
        "path": str(final.resolve()),
        "donor_start": round(start, 3),
        "donor_end": round(end, 3),
        "duration_seconds": round(out_dur, 3),
        "looped": loop_to_seconds is not None and loop_to_seconds > dur,
        "agent_note": "Place on audio track under dialogue; apply gain -6..-12 dB.",
    }
