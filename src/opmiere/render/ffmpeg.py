"""FFmpegBackend — the P0/P1 render engine (ARCHITECTURE.md section 5.2).

P0/P1 scope, deliberately narrow (see ARCHITECTURE.md section 9):
  - at most one video track and one audio track
  - clips on a track must be placed back-to-back with no gaps or overlaps,
    starting at frame 0 ("sequential placement")
  - trim + concat, plus the section 5.8 deterministic effects that don't
    change a clip's timeline duration: color/text (video), gain (audio), and
    fade in/out (video + audio). Speed/time-remap and cross-clip transitions
    are later work — see model.KNOWN_EFFECT_TYPES for why they're excluded.

Also provides ``import_media``: probes a source file with ffprobe and registers
it on the project, refusing to guess values ffprobe doesn't confirm.
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from ..bundle import Bundle
from ..model import DEFAULT_TEXT_FONT, IMAGE_VIRTUAL_DURATION_FRAMES, Media, MediaKind, Project, Track
from .backend import RenderBackend
from .probe import ProbeResult, probe, require_ffmpeg_tools

__all__ = ["FFmpegBackend", "import_media"]

# x/y position expressions for the "text" effect's ffmpeg drawtext filter.
_TEXT_POSITION_EXPRESSIONS = {
    "top": ("(w-text_w)/2", "40"),
    "center": ("(w-text_w)/2", "(h-text_h)/2"),
    "bottom": ("(w-text_w)/2", "h-text_h-40"),
}


def _escape_filter_path(path: str) -> str:
    """Make a filesystem path safe inside a single-quoted ffmpeg filter value.

    Verified empirically on Windows (drive-letter colons and backslashes are
    both filtergraph metacharacters and are *not* reliably escapable when the
    value is left unquoted — quoting the whole value plus this escaping is
    the combination that actually parses).
    """
    return path.replace("\\", "/").replace(":", "\\:")


def _effect_filters(
    effects: list[dict[str, Any]],
    clip_duration_frames: int,
    fps: float,
    stream: Literal["video", "audio"],
    text_dir: Path | None = None,
) -> list[str]:
    """Translate a clip's ``effects`` list into ffmpeg filter fragments.

    Each effect dict may contribute to the video chain, the audio chain, both,
    or neither, depending on ``stream`` — e.g. "fade" produces a video `fade`
    filter when building the video stream and an `afade` filter when building
    the audio stream from the very same effect dict, so "fade this clip" does
    what it sounds like on both picture and sound.

    ``text_dir`` is a scratch directory the caller owns for the render's
    lifetime: caption text is written there as a UTF-8 file and referenced via
    drawtext's ``textfile=``, sidestepping two real problems verified on
    Windows — CJK characters getting mangled when passed through subprocess
    argv (the OS console codepage, not UTF-8, decides that), and having to
    hand-escape arbitrary user text for the filtergraph's own mini-syntax.
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
        elif etype == "gain":
            if stream != "audio":
                continue
            db = effect.get("db")
            if not isinstance(db, (int, float)):
                raise ValueError("gain effect has invalid 'db' value")
            parts.append(f"volume={db}dB")
        elif etype == "text":
            if stream != "video":
                continue
            content = effect.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("text effect has invalid 'content'")
            position = effect.get("position", "bottom")
            if position not in _TEXT_POSITION_EXPRESSIONS:
                raise ValueError(f"text effect has invalid position {position!r}")
            size = effect.get("size", 48)
            color = effect.get("color", "white")
            font = effect.get("font", DEFAULT_TEXT_FONT)
            if not Path(font).exists():
                raise FileNotFoundError(
                    f"text effect font not found: {font} "
                    "(pass an explicit 'font' path to an existing .ttf/.ttc)"
                )
            if text_dir is None:
                raise RuntimeError("internal: _effect_filters needs text_dir for a text effect")
            caption_path = Path(text_dir) / f"caption_{uuid.uuid4().hex[:8]}.txt"
            caption_path.write_text(content, encoding="utf-8")
            x_expr, y_expr = _TEXT_POSITION_EXPRESSIONS[position]
            parts.append(
                f"drawtext=fontfile='{_escape_filter_path(font)}':"
                f"textfile='{_escape_filter_path(str(caption_path))}':"
                f"fontcolor={color}:fontsize={size}:x={x_expr}:y={y_expr}:expansion=none"
            )
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


def _speed_filter(speed: float, stream: Literal["video", "audio"]) -> str | None:
    """A setpts (video) or atempo (audio) fragment for a clip's speed, or
    None at normal speed so the filter chain is unchanged for the common
    (speed == 1.0) case. Must run before effects/scale in the chain, since
    effect timing (e.g. fade) is computed against the post-speed timeline
    duration (see Clip.timeline_duration_frames)."""
    if speed == 1.0:
        return None
    if stream == "video":
        return f"setpts=(PTS-STARTPTS)/{speed}"
    # atempo supports 0.5-2.0 in a single filter instance; chaining several
    # instances for a wider range is real, well-known ffmpeg practice but
    # out of scope for this pass - fail clearly rather than let ffmpeg do it.
    if not (0.5 <= speed <= 2.0):
        raise ValueError(
            f"audio speed {speed} is outside ffmpeg's single-atempo range "
            "[0.5, 2.0]; chaining atempo filters for a wider range isn't implemented yet"
        )
    return f"atempo={speed}"


def _validate_contiguous(track: Track) -> list:
    """Each clip must either hard-cut from the previous one (start == prev.end)
    or declare a transition_in whose duration_frames exactly explains the
    overlap (start == prev.end - duration_frames). Anything else — an
    undeclared overlap or a gap — is rejected rather than silently rendered.
    """
    clips = track.clips_in_order()
    if not clips:
        raise ValueError(f"track {track.id} has no clips")
    if clips[0].start != 0:
        raise ValueError(
            f"P0 limitation: track {track.id} must start at frame 0 "
            f"(sequential placement only); first clip starts at {clips[0].start}"
        )
    for prev, nxt in zip(clips, clips[1:]):
        if nxt.start == prev.end:
            continue
        transition = nxt.transition_in
        if transition is not None and nxt.start == prev.end - transition["duration_frames"]:
            continue
        raise ValueError(
            f"P0 limitation: track {track.id} clips must be contiguous, "
            f"optionally overlapping by exactly a declared transition_in "
            f"duration; clip {prev.id} ends at frame {prev.end} but {nxt.id} "
            f"starts at frame {nxt.start}"
        )
    return clips


def _track_all_media_have_audio(project: Project, track: Track) -> bool:
    return bool(track.clips) and all(
        project.media_by_id(c.media).has_audio for c in track.clips
    )


def _fold_segments(
    labels: list[str],
    clips: list,
    fps: float,
    stream: Literal["video", "audio"],
    final_label: str,
) -> list[str]:
    """Pairwise-fold N already-processed segment labels into one.

    Each boundary is either a plain hard-cut (ffmpeg `concat`) or, when the
    next clip declares a transition_in, a real crossfade (`xfade` for video,
    `acrossfade` for audio) — verified empirically: xfade needs an explicit
    `offset` in seconds (how far into the *running* combined stream the
    dissolve starts) while acrossfade infers it from `duration` alone; get
    either wrong and the dissolve lands at the wrong point or not at all.
    concat is associative, so pairwise-folding hard cuts produces the same
    output as one big concat=n=N — this only changes behavior at declared
    transitions.
    """
    parts: list[str] = []
    running = labels[0]
    running_duration_frames = clips[0].timeline_duration_frames
    for i in range(1, len(labels)):
        clip = clips[i]
        out_label = final_label if i == len(labels) - 1 else f"{stream[0]}fold{i}"
        transition = clip.transition_in
        if transition is not None:
            t_frames = transition["duration_frames"]
            duration_s = t_frames / fps
            if stream == "video":
                offset_s = running_duration_frames / fps - duration_s
                parts.append(
                    f"[{running}][{labels[i]}]xfade=transition=fade:"
                    f"duration={duration_s:.6f}:offset={offset_s:.6f}[{out_label}]"
                )
            else:
                parts.append(f"[{running}][{labels[i]}]acrossfade=d={duration_s:.6f}[{out_label}]")
            running_duration_frames += clip.timeline_duration_frames - t_frames
        else:
            va = "v=1:a=0" if stream == "video" else "v=0:a=1"
            parts.append(f"[{running}][{labels[i]}]concat=n=2:{va}[{out_label}]")
            running_duration_frames += clip.timeline_duration_frames
        running = out_label
    return parts


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

        fps = project.timebase.fps

        input_args: list[str] = []
        media_index: dict[str, int] = {}
        for i, media_id in enumerate(media_order):
            media = project.media_by_id(media_id)
            if media.kind == "image":
                # -loop turns the single still frame into an indefinite video
                # stream at the project's fps; everything downstream (trim,
                # effects, scale/pad) then treats it exactly like any other
                # [idx:v] video stream — no other change needed.
                input_args += ["-loop", "1", "-framerate", str(fps), "-i", str(bundle.media_path(media.path))]
            else:
                input_args += ["-i", str(bundle.media_path(media.path))]
            media_index[media_id] = i

        filter_parts: list[str] = []
        W, H = project.resolution.w, project.resolution.h

        # Scratch dir for "text" effect caption files (see _effect_filters);
        # must outlive the ffmpeg subprocess call below, so it wraps everything
        # that reads from it.
        with tempfile.TemporaryDirectory(prefix="opmiere_render_") as _text_dir:
            text_dir = Path(_text_dir)

            video_final_label: str | None = None
            vlabels: list[str] = []
            if video_track is not None:
                for n, clip in enumerate(video_clips):
                    idx = media_index[clip.media]
                    label = f"v{n}"
                    fx = _effect_filters(clip.effects, clip.timeline_duration_frames, fps, "video", text_dir)
                    speed_pts = _speed_filter(clip.speed, "video") or "setpts=PTS-STARTPTS"
                    chain = (
                        f"[{idx}:v]trim=start_frame={clip.src_in}:end_frame={clip.src_out},"
                        f"{speed_pts}"
                    )
                    for filt in fx:
                        chain += f",{filt}"
                    chain += (
                        f",scale={W}:{H}:force_original_aspect_ratio=decrease,"
                        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"setsar=1,fps={fps}[{label}]"
                    )
                    filter_parts.append(chain)
                    vlabels.append(label)
                if len(vlabels) == 1:
                    video_final_label = vlabels[0]
                else:
                    filter_parts.extend(_fold_segments(vlabels, video_clips, fps, "video", "vout"))
                    video_final_label = "vout"

            audio_final_label: str | None = None
            alabels: list[str] = []
            if audio_source_track is not None:
                sample_rate = project.timebase.sample_rate
                tb = project.timebase
                audio_clips = audio_source_track.clips_in_order()
                for n, clip in enumerate(audio_clips):
                    idx = media_index[clip.media]
                    label = f"a{n}"
                    start_s = tb.frames_to_seconds(clip.src_in)
                    end_s = tb.frames_to_seconds(clip.src_out)
                    fx = _effect_filters(clip.effects, clip.timeline_duration_frames, fps, "audio", text_dir)
                    chain = (
                        f"[{idx}:a]atrim=start={start_s:.6f}:end={end_s:.6f},"
                        f"asetpts=PTS-STARTPTS"
                    )
                    speed_tempo = _speed_filter(clip.speed, "audio")
                    if speed_tempo:
                        chain += f",{speed_tempo}"
                    for filt in fx:
                        chain += f",{filt}"
                    chain += f",aresample={sample_rate}[{label}]"
                    filter_parts.append(chain)
                    alabels.append(label)
                if len(alabels) == 1:
                    audio_final_label = alabels[0]
                else:
                    filter_parts.extend(_fold_segments(alabels, audio_clips, fps, "audio", "aout"))
                    audio_final_label = "aout"

            filter_complex = ";".join(filter_parts)

            cmd = ["ffmpeg", "-y", *input_args, "-filter_complex", filter_complex]
            if video_final_label:
                cmd += ["-map", f"[{video_final_label}]"]
            if audio_final_label:
                cmd += ["-map", f"[{audio_final_label}]"]
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
    origin: dict[str, Any] | None = None,
) -> Media:
    """Copy ``src_path`` into the bundle and register it on the project.

    For kind="video"/"audio", every field is filled from a real ffprobe
    result — never guessed. For kind="video" specifically, the source fps
    must match the project's timebase fps; P0's FFmpegBackend trims by frame
    number and assumes they agree (frame-rate conversion is future work).

    kind="image" is different in kind, not just degree: a still image has no
    intrinsic duration to probe, so it gets IMAGE_VIRTUAL_DURATION_FRAMES
    instead (see model.py for why that's a deliberate convention, not a
    guess) and skips ffprobe entirely.

    ``origin`` records how a generated asset came to exist (see model.Media);
    None for ordinary imports of the user's own files.
    """
    require_ffmpeg_tools()
    src_path = Path(src_path)

    if kind == "image":
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        dest = bundle.import_file(src_path, dest_name=dest_name)
        rel_path = dest.relative_to(bundle.media_dir).as_posix()
        return project.add_media(
            kind="image",
            path=rel_path,
            duration_frames=IMAGE_VIRTUAL_DURATION_FRAMES,
            has_audio=False,
            origin=origin,
        )

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
        raise ValueError(f"unknown media kind {kind!r}")

    dest = bundle.import_file(src_path, dest_name=dest_name)
    duration_frames = project.timebase.seconds_to_frames(result.duration_seconds)
    rel_path = dest.relative_to(bundle.media_dir).as_posix()
    return project.add_media(
        kind=kind,
        path=rel_path,
        duration_frames=duration_frames,
        has_audio=result.has_audio,
        origin=origin,
    )
