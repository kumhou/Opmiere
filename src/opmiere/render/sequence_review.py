"""Sequence-level eyes: contact sheet across the cut + structural review_cut.

Per-file make_contact_sheet / quality_check cannot see "does this assemble into
one film?" This module samples the base video track so the agent can judge
pacing, continuity jumps, and craft issues before calling a cut final.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .probe import require_ffmpeg_tools

if TYPE_CHECKING:
    from ..bundle import Bundle
    from ..model import Project

__all__ = ["make_sequence_contact_sheet", "review_cut", "sample_frame_yavg"]


def sample_frame_yavg(media_path: Path, time_seconds: float) -> float | None:
    """Mean luma (YAVG) at one timestamp — for adjacent-shot jump detection."""
    require_ffmpeg_tools()
    t = max(0.0, float(time_seconds))
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-ss", f"{t:.3f}", "-i", str(media_path),
            "-frames:v", "1", "-vf", "signalstats,metadata=print:file=-",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    text = (proc.stderr or "") + (proc.stdout or "")
    for line in text.splitlines():
        if "YAVG" not in line:
            continue
        for part in line.replace(":", "=").split():
            if "YAVG" in part and "=" in part:
                try:
                    return float(part.split("=")[-1])
                except ValueError:
                    continue
        if "=" in line:
            try:
                return float(line.strip().split("=")[-1])
            except ValueError:
                pass
    return None


def review_cut(
    project: "Project",
    bundle: "Bundle | None" = None,
    *,
    min_clip_seconds: float = 0.4,
    max_brightness_jump: float = 45.0,
    check_brightness_jumps: bool = True,
    expect_music_duck: bool = True,
) -> dict[str, Any]:
    """Structural + optional pixel jump review of the current timeline."""
    fps = float(project.timebase.fps or 30.0)
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    video_tracks = [t for t in project.tracks if t.kind == "video"]
    audio_tracks = [t for t in project.tracks if t.kind == "audio"]
    base_video = video_tracks[0] if video_tracks else None

    if base_video is None:
        issues.append({
            "severity": "error",
            "code": "no_video_track",
            "message": "no video track — cut has no picture spine",
        })
    else:
        clips = base_video.clips_in_order()
        if not clips:
            issues.append({
                "severity": "error",
                "code": "empty_base",
                "message": "base video track has no clips",
            })
        for i, clip in enumerate(clips):
            dur_s = clip.timeline_duration_frames / fps
            if dur_s < min_clip_seconds and clip.timeline_duration_frames > 0:
                issues.append({
                    "severity": "warning",
                    "code": "short_clip",
                    "clip_id": clip.id,
                    "index": i,
                    "duration_seconds": round(dur_s, 3),
                    "message": (
                        f"clip {clip.id} is only {dur_s:.2f}s "
                        f"(< {min_clip_seconds}s) — may feel like a flash cut"
                    ),
                })
            if i > 0:
                prev = clips[i - 1]
                expected_start = prev.end
                if clip.transition_in:
                    expected_start = prev.end - int(
                        clip.transition_in["duration_frames"]
                    )
                if clip.start != expected_start:
                    issues.append({
                        "severity": "error",
                        "code": "gap_or_overlap",
                        "clip_id": clip.id,
                        "message": (
                            f"clip {clip.id} start={clip.start} but expected "
                            f"{expected_start} after {prev.id} — gap/overlap"
                        ),
                    })

        if check_brightness_jumps and bundle is not None and len(clips) >= 2:
            for i in range(1, len(clips)):
                prev, nxt = clips[i - 1], clips[i]
                if nxt.transition_in:
                    continue
                try:
                    prev_media = project.media_by_id(prev.media)
                    next_media = project.media_by_id(nxt.media)
                    prev_path = bundle.media_path(prev_media.path)
                    next_path = bundle.media_path(next_media.path)
                    prev_t = project.timebase.frames_to_seconds(
                        max(prev.src_in, prev.src_out - 1)
                    )
                    next_t = project.timebase.frames_to_seconds(nxt.src_in)
                    y0 = sample_frame_yavg(prev_path, prev_t)
                    y1 = sample_frame_yavg(next_path, next_t)
                    if y0 is not None and y1 is not None:
                        jump = abs(y1 - y0)
                        if jump >= max_brightness_jump:
                            issues.append({
                                "severity": "warning",
                                "code": "brightness_jump",
                                "from_clip": prev.id,
                                "to_clip": nxt.id,
                                "yavg_from": round(y0, 1),
                                "yavg_to": round(y1, 1),
                                "jump": round(jump, 1),
                                "message": (
                                    f"hard cut {prev.id}→{nxt.id} luma jump "
                                    f"{jump:.0f} (>{max_brightness_jump:g}) — "
                                    f"consider cross_dissolve or grade match"
                                ),
                            })
                except Exception as e:
                    warnings.append(f"brightness sample failed at cut {i}: {e}")

    if expect_music_duck and audio_tracks:
        has_duck = any(t.duck for t in audio_tracks)
        if len(audio_tracks) >= 2 and not has_duck:
            issues.append({
                "severity": "warning",
                "code": "no_ducking",
                "message": (
                    "multiple audio tracks but no set_ducking — music may "
                    "mask dialogue; call set_ducking(music, vo)"
                ),
            })

    if len(video_tracks) > 1 and base_video and not base_video.clips:
        issues.append({
            "severity": "error",
            "code": "overlay_without_base",
            "message": "overlay video tracks exist but base is empty",
        })

    total_frames = project.duration_frames()
    total_s = total_frames / fps if fps else 0.0
    n_base = len(base_video.clips) if base_video else 0
    errors = [i for i in issues if i.get("severity") == "error"]
    warn_items = [i for i in issues if i.get("severity") == "warning"]

    return {
        "ok": len(errors) == 0,
        "duration_frames": total_frames,
        "duration_seconds": round(total_s, 3),
        "base_clip_count": n_base,
        "video_track_count": len(video_tracks),
        "audio_track_count": len(audio_tracks),
        "issues": issues,
        "error_count": len(errors),
        "warning_count": len(warn_items),
        "warnings": warnings,
        "agent_note": (
            "Fix severity=error before export. Review warnings for craft. "
            "Pair with make_sequence_contact_sheet + delivery_check on export."
        ),
    }


def make_sequence_contact_sheet(
    project: "Project",
    bundle: "Bundle",
    output_path: Path | str,
    *,
    max_tiles: int = 12,
    tile_width: int = 160,
    tile_height: int = 90,
    cols: int | None = None,
) -> dict[str, Any]:
    """One grid image: mid-frame of each base-track clip (time order)."""
    require_ffmpeg_tools()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_tracks = [t for t in project.tracks if t.kind == "video"]
    if not video_tracks:
        raise ValueError("project has no video track for sequence contact sheet")
    base = video_tracks[0]
    clips = base.clips_in_order()
    if not clips:
        raise ValueError("base video track has no clips")

    if len(clips) > max_tiles:
        step = len(clips) / max_tiles
        chosen = [clips[int(i * step)] for i in range(max_tiles)]
    else:
        chosen = list(clips)

    n = len(chosen)
    if cols is None:
        cols = min(4, max(1, n))
    cols = max(1, int(cols))
    rows = (n + cols - 1) // cols
    cell = f"{tile_width}x{tile_height}"
    scale_pad = (
        f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=decrease,"
        f"pad={tile_width}:{tile_height}:(ow-iw)/2:(oh-ih)/2"
    )

    labels: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="opmiere_seq_cs_") as tmp:
        tmp_path = Path(tmp)
        thumbs: list[Path] = []
        for i, clip in enumerate(chosen):
            media = project.media_by_id(clip.media)
            media_file = bundle.media_path(media.path)
            mid_frame = (clip.src_in + clip.src_out) // 2
            t = project.timebase.frames_to_seconds(mid_frame)
            thumb = tmp_path / f"t{i:03d}.png"
            ok = False
            for ss_args in (
                ["-ss", f"{t:.3f}", "-i", str(media_file)],
                ["-i", str(media_file)],
            ):
                proc = subprocess.run(
                    [
                        "ffmpeg", "-y", "-hide_banner",
                        *ss_args,
                        "-frames:v", "1",
                        "-vf", scale_pad,
                        str(thumb),
                    ],
                    capture_output=True,
                    text=True,
                )
                if (
                    proc.returncode == 0
                    and thumb.exists()
                    and thumb.stat().st_size > 0
                ):
                    ok = True
                    break
            if not ok:
                raise RuntimeError(
                    f"failed to extract thumb for clip {clip.id} from {media_file}"
                )
            thumbs.append(thumb)
            labels.append({
                "index": i,
                "clip_id": clip.id,
                "media_id": media.id,
                "timeline_start": clip.start,
                "src_mid_seconds": round(t, 3),
            })

        while len(thumbs) < cols * rows:
            pad = tmp_path / f"pad{len(thumbs)}.png"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"color=c=black:s={cell}",
                    "-frames:v", "1", str(pad),
                ],
                capture_output=True, text=True, check=True,
            )
            thumbs.append(pad)

        cmd: list[str] = ["ffmpeg", "-y", "-hide_banner"]
        for th in thumbs:
            cmd += ["-i", str(th)]
        n_in = len(thumbs)
        labels_in = "".join(f"[{i}:v]" for i in range(n_in))
        fc = f"{labels_in}concat=n={n_in}:v=1:a=0,tile={cols}x{rows}[vout]"
        cmd += [
            "-filter_complex", fc,
            "-map", "[vout]",
            "-frames:v", "1",
            str(output_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                f"sequence contact sheet assemble failed:\n{proc.stderr[-2500:]}"
            )

    return {
        "path": str(output_path.resolve()),
        "cols": cols,
        "rows": rows,
        "tile_count": n,
        "tiles": labels,
        "agent_note": (
            "Read this image to judge the whole cut's pacing and continuity. "
            "Not a substitute for delivery_check on the export file."
        ),
    }
