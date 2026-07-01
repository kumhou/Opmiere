"""FFmpegBackend — the P0/P1 render engine (ARCHITECTURE.md section 5.2).

P0/P1 scope, deliberately narrow (see ARCHITECTURE.md section 9):
  - at most one video track and one audio track
  - clips on a track must be placed back-to-back with no gaps or overlaps,
    starting at frame 0 ("sequential placement")
  - trim + concat, plus the section 5.8 deterministic effects that don't
    change a clip's timeline duration: color (video) and fade in/out (video
    + audio). Speed/time-remap and cross-clip transitions are later work —
    see model.KNOWN_EFFECT_TYPES for why they're excluded for now.

Also provides ``import_media``: probes a source file with ffprobe and registers
it on the project, refusing to guess values ffprobe doesn't confirm.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Literal

from ..bundle import Bundle
from ..model import Media, MediaKind, Project, Track
from .backend import RenderBackend
from .probe import ProbeResult, probe, require_ffmpeg_tools

__all__ = ["FFmpegBackend", "import_media"]


def _effect_filters(
    effects: list[dict[str, Any]],
    clip_duration_frames: int,
    fps: float,
    stream: Literal["video", "audio"],
) -> list[str]:
    """Translate a clip's ``effects`` list into ffmpeg filter fragments.

    Each effect dict may contribute to the video chain, the audio chain, both,
    or neither, depending on ``stream`` — e.g. "fade" produces a video `fade`
    filter when building the video stream and an `afade` filter when building
    the audio stream from the very same effect dict, so "fade this clip" does
    what it sounds like on both picture and sound.
    """
    parts: list[str] = []
    for effect in effects:
        etype = effect.get("type")
        if etype == "color":
            if stream != "video":
                continue
            brightness = effect.get("brightness", 0.0)
            contrast = effect.get("contrast", 1.0)
            saturation = effect.get("saturation", 1.0)
            parts.append(f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation}")
        elif etype == "fade":
            direction = effect.get("direction")
            duration_frames = effect.get("duration_frames")
            # Editor.apply_effect already validated these; re-checking here
            # means a render is never corrupted by a project.json hand-edited
            # (or trimmed shorter after the fade was applied) outside the API.
            if direction not in ("in", "out"):
                raise ValueError(f"fade effect has invalid direction {direction!r}")
            if not isinstance(duration_frames, int) or duration_frames <= 0:
                raise ValueError("fade effect has invalid duration_frames")
            if duration_frames > clip_duration_frames:
                raise ValueError(
                    f"fade duration_frames ({duration_frames}) exceeds clip "
                    f"duration ({clip_duration_frames}) at render time"
                )
            duration_s = duration_frames / fps
            start_s = 0.0 if direction == "in" else (clip_duration_frames - duration_frames) / fps
            filter_name = "fade" if stream == "video" else "afade"
            parts.append(f"{filter_name}=t={direction}:st={start_s:.6f}:d={duration_s:.6f}")
        else:
            raise NotImplementedError(f"effect type {etype!r} is not supported by FFmpegBackend yet")
    return parts


def _validate_contiguous(track: Track) -> list:
    clips = track.clips_in_order()
    if not clips:
        raise ValueError(f"track {track.id} has no clips")
    if clips[0].start != 0:
        raise ValueError(
            f"P0 limitation: track {track.id} must start at frame 0 "
            f"(sequential placement only); first clip starts at {clips[0].start}"
        )
    for prev, nxt in zip(clips, clips[1:]):
        if nxt.start != prev.end:
            raise ValueError(
                f"P0 limitation: track {track.id} clips must be contiguous "
                f"(no gaps/overlaps); clip {prev.id} ends at frame {prev.end} "
                f"but {nxt.id} starts at frame {nxt.start}"
            )
    return clips


def _track_all_media_have_audio(project: Project, track: Track) -> bool:
    return bool(track.clips) and all(
        project.media_by_id(c.media).has_audio for c in track.clips
    )


class FFmpegBackend(RenderBackend):
    def export(self, project: Project, bundle: Bundle, output_path: Path) -> Path:
        require_ffmpeg_tools()
        output_path = Path(output_path)

        video_tracks = [t for t in project.tracks if t.kind == "video"]
        audio_tracks = [t for t in project.tracks if t.kind == "audio"]
        if len(video_tracks) > 1 or len(audio_tracks) > 1:
            raise NotImplementedError(
                "P0 FFmpegBackend supports at most one video track and one "
                "audio track (multi-track lands in a later phase)"
            )
        video_track = video_tracks[0] if video_tracks else None
        audio_track = audio_tracks[0] if audio_tracks else None
        if video_track is None and audio_track is None:
            raise ValueError("project has no tracks to render")

        video_clips = _validate_contiguous(video_track) if video_track else []
        if audio_track:
            _validate_contiguous(audio_track)

        # Separate audio track wins; otherwise fall back to the video track's
        # own embedded audio if every clip on it actually has audio.
        audio_source_track = audio_track
        if audio_source_track is None and video_track is not None:
            audio_source_track = (
                video_track if _track_all_media_have_audio(project, video_track) else None
            )

        # One -i per unique media file, in order of first appearance.
        media_order: list[str] = []
        seen: set[str] = set()
        for track in (video_track, audio_source_track):
            if track is None:
                continue
            for clip in track.clips_in_order():
                if clip.media not in seen:
                    seen.add(clip.media)
                    media_order.append(clip.media)

        input_args: list[str] = []
        media_index: dict[str, int] = {}
        for i, media_id in enumerate(media_order):
            media = project.media_by_id(media_id)
            input_args += ["-i", str(bundle.media_path(media.path))]
            media_index[media_id] = i

        filter_parts: list[str] = []
        W, H = project.resolution.w, project.resolution.h
        fps = project.timebase.fps

        vlabels: list[str] = []
        if video_track is not None:
            for n, clip in enumerate(video_clips):
                idx = media_index[clip.media]
                label = f"v{n}"
                fx = _effect_filters(clip.effects, clip.duration_frames, fps, "video")
                chain = (
                    f"[{idx}:v]trim=start_frame={clip.src_in}:end_frame={clip.src_out},"
                    f"setpts=PTS-STARTPTS"
                )
                for filt in fx:
                    chain += f",{filt}"
                chain += (
                    f",scale={W}:{H}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"setsar=1,fps={fps}[{label}]"
                )
                filter_parts.append(chain)
                vlabels.append(f"[{label}]")
            filter_parts.append(
                "".join(vlabels) + f"concat=n={len(vlabels)}:v=1:a=0[vout]"
            )

        alabels: list[str] = []
        if audio_source_track is not None:
            sample_rate = project.timebase.sample_rate
            tb = project.timebase
            for n, clip in enumerate(audio_source_track.clips_in_order()):
                idx = media_index[clip.media]
                label = f"a{n}"
                start_s = tb.frames_to_seconds(clip.src_in)
                end_s = tb.frames_to_seconds(clip.src_out)
                fx = _effect_filters(clip.effects, clip.duration_frames, fps, "audio")
                chain = (
                    f"[{idx}:a]atrim=start={start_s:.6f}:end={end_s:.6f},"
                    f"asetpts=PTS-STARTPTS"
                )
                for filt in fx:
                    chain += f",{filt}"
                chain += f",aresample={sample_rate}[{label}]"
                filter_parts.append(chain)
                alabels.append(f"[{label}]")
            filter_parts.append(
                "".join(alabels) + f"concat=n={len(alabels)}:v=0:a=1[aout]"
            )

        filter_complex = ";".join(filter_parts)

        cmd = ["ffmpeg", "-y", *input_args, "-filter_complex", filter_complex]
        if vlabels:
            cmd += ["-map", "[vout]"]
        if alabels:
            cmd += ["-map", "[aout]"]
        else:
            cmd += ["-an"]
        cmd += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(output_path)]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "ffmpeg export failed (exit "
                f"{proc.returncode}):\ncmd: {' '.join(cmd)}\nstderr:\n{proc.stderr}"
            )
        return output_path


def import_media(
    bundle: Bundle,
    project: Project,
    src_path: Path,
    kind: MediaKind,
    dest_name: str | None = None,
) -> Media:
    """Copy ``src_path`` into the bundle and register it on the project.

    Every field is filled from a real ffprobe result — never guessed. For
    kind="video", the source fps must match the project's timebase fps; P0's
    FFmpegBackend trims by frame number and assumes they agree (frame-rate
    conversion is future work).
    """
    require_ffmpeg_tools()
    src_path = Path(src_path)
    result: ProbeResult = probe(src_path)

    if kind == "video":
        if not result.has_video:
            raise ValueError(f"{src_path} has no video stream; cannot import as kind='video'")
        fps = result.fps or 0.0
        if abs(fps - project.timebase.fps) > 0.01:
            raise ValueError(
                f"P0 limitation: source fps {fps:.3f} does not match project "
                f"fps {project.timebase.fps:.3f} ({src_path}). Re-encode to "
                "match, or wait for frame-rate conversion in a later phase."
            )
    elif kind == "audio":
        if not result.has_audio:
            raise ValueError(f"{src_path} has no audio stream; cannot import as kind='audio'")
    else:
        raise NotImplementedError(
            f"P0 import_media does not support kind={kind!r} yet "
            "(image import lands with generation in P2)"
        )

    dest = bundle.import_file(src_path, dest_name=dest_name)
    duration_frames = project.timebase.seconds_to_frames(result.duration_seconds)
    rel_path = dest.relative_to(bundle.media_dir).as_posix()
    return project.add_media(
        kind=kind,
        path=rel_path,
        duration_frames=duration_frames,
        has_audio=result.has_audio,
    )
