"""FFmpegBackend — the P0/P1 render engine (ARCHITECTURE.md section 5.2).

Track semantics (video and audio share one convention):
  - the *first* track of a kind is the base layer: clips contiguous from
    frame 0, hard cuts or declared transitions only (_validate_contiguous).
  - every later track of that kind is an overlay: gaps allowed, clips just
    can't overlap each other on the same track (_validate_no_overlaps).
    Overlay video composites via `overlay`; overlay audio is delayed to its
    timeline position (`adelay`) and summed into the mix (`amix`).
  - an audio track may duck against another (model.Track.duck) — compiled to
    `sidechaincompress` keyed by a split of the other track's pre-duck
    submix (pre-duck keys mean two tracks ducking against each other can
    never form a filtergraph cycle).

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
from ..model import (
    CURVES_PRESETS,
    DEFAULT_TEXT_FONT,
    IMAGE_VIRTUAL_DURATION_FRAMES,
    SHAPE_MASK_SHAPES,
    Clip,
    Media,
    MediaKind,
    Project,
    Track,
)
from .backend import RenderBackend
from .hwencode import hwaccel_input_args, video_encode_args
from .probe import ProbeResult, probe, require_ffmpeg_tools

__all__ = ["FFmpegBackend", "import_media", "conform_to_project_timebase"]

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
    out_w: int | None = None,
    out_h: int | None = None,
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

    ``out_w``/``out_h`` are the target box size for effects that must emit a
    fixed pixel size (currently ``ken_burns`` via zoompan). Passed from
    ``_video_clip_chain``; unused by linear filters.
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
            # A dark border by default: captions almost always need one to stay
            # readable over bright/busy footage (found the hard way on《雨后》's
            # golden shot3 — plain white text washed out). drawtext gives this
            # natively via borderw/bordercolor; border_width=0 opts out.
            border_width = effect.get("border_width", 2)
            border_color = effect.get("border_color", "black")
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
                f"fontcolor={color}:fontsize={size}:"
                f"borderw={border_width}:bordercolor={border_color}:"
                f"x={x_expr}:y={y_expr}:expansion=none"
            )
        elif etype == "subtitles":
            if stream != "video":
                continue
            # Burn timed captions from .srt/.ass (transcribe → write_srt → here).
            # ffmpeg subtitles filter; path escaping matches drawtext on Windows.
            path = effect.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("subtitles effect has invalid 'path'")
            if not Path(path).exists():
                raise FileNotFoundError(f"subtitles effect path not found: {path}")
            force_style = effect.get("force_style")
            frag = f"subtitles='{_escape_filter_path(path)}'"
            if isinstance(force_style, str) and force_style.strip():
                # force_style uses single quotes inside the filter value —
                # strip quotes from user input to avoid breaking the graph.
                style = force_style.replace("'", "")
                frag += f":force_style='{style}'"
            parts.append(frag)
        elif etype == "blur":
            if stream != "video":
                continue
            amount = effect.get("amount", 5.0)
            if not isinstance(amount, (int, float)) or amount <= 0:
                raise ValueError("blur effect has invalid 'amount'")
            parts.append(f"gblur=sigma={amount}")
        elif etype == "vignette":
            if stream != "video":
                continue
            strength = effect.get("strength", 1.0)
            if not isinstance(strength, (int, float)) or strength <= 0:
                raise ValueError("vignette effect has invalid 'strength'")
            # ffmpeg's vignette angle param: PI/5 is its own default "normal"
            # strength: scale that by 1/strength so bigger strength = a
            # smaller (more aggressive) angle = a more visible vignette.
            parts.append(f"vignette=angle=PI/5/{strength}")
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
        elif etype == "chroma_key":
            if stream != "video":
                continue
            color = effect.get("color", "green")
            similarity = effect.get("similarity", 0.15)
            blend = effect.get("blend", 0.05)
            if not isinstance(similarity, (int, float)) or not (0.0 < similarity <= 1.0):
                raise ValueError("chroma_key effect has invalid 'similarity'")
            if not isinstance(blend, (int, float)) or not (0.0 <= blend <= 1.0):
                raise ValueError("chroma_key effect has invalid 'blend'")
            # Keys transparency into the frame - _video_clip_chain switches to
            # a transparent pad color + an explicit alpha pixel format for any
            # clip carrying this effect, or the alpha this produces would be
            # silently dropped (or worse, padded with *opaque* black) before
            # the overlay compositing step ever sees it. Verified with a real
            # spike (solid-color background + greenscreen "subject" clip,
            # composited and eyeballed) before wiring this in - alpha survival
            # through scale/pad/overlay is not something to assume.
            parts.append(f"chromakey=color={color}:similarity={similarity}:blend={blend}")
        elif etype == "luma_key":
            if stream != "video":
                continue
            threshold = effect.get("threshold", 0.1)
            tolerance = effect.get("tolerance", 0.1)
            if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
                raise ValueError("luma_key effect has invalid 'threshold'")
            if not isinstance(tolerance, (int, float)) or not (0.0 <= tolerance <= 1.0):
                raise ValueError("luma_key effect has invalid 'tolerance'")
            # Same alpha-survival requirement as chroma_key (see above) -
            # _video_clip_chain's has_alpha check covers both.
            parts.append(f"lumakey=threshold={threshold}:tolerance={tolerance}")
        elif etype == "curves":
            if stream != "video":
                continue
            preset = effect.get("preset")
            if preset not in CURVES_PRESETS:
                raise ValueError(f"curves effect has invalid 'preset' {preset!r}")
            parts.append(f"curves=preset={preset}")
        elif etype == "crop":
            if stream != "video":
                continue
            width, height = effect.get("width"), effect.get("height")
            if not isinstance(width, int) or width <= 0:
                raise ValueError("crop effect has invalid 'width'")
            if not isinstance(height, int) or height <= 0:
                raise ValueError("crop effect has invalid 'height'")
            # x/y default to ffmpeg's own centered-crop expressions; always
            # emitted explicitly (not left to the filter's own defaults) so
            # "only x given" / "only y given" both do the obvious thing.
            x_expr = effect.get("x", "(in_w-out_w)/2")
            y_expr = effect.get("y", "(in_h-out_h)/2")
            parts.append(f"crop={width}:{height}:{x_expr}:{y_expr}")
        elif etype == "rotate":
            if stream != "video":
                continue
            degrees = effect.get("degrees")
            fill = effect.get("fill", "black")
            if not isinstance(degrees, (int, float)):
                raise ValueError("rotate effect has invalid 'degrees'")
            # Output stays the clip's own current size (corners may clip),
            # not auto-expanded to fit the rotated rectangle - matches how
            # rotation works in most simple video editors, and keeps every
            # clip's frame size predictable for the scale/pad step after it.
            parts.append(f"rotate={degrees}*PI/180:fillcolor={fill}")
        elif etype == "sharpen":
            if stream != "video":
                continue
            amount = effect.get("amount", 1.0)
            if not isinstance(amount, (int, float)) or not (0.0 < amount <= 5.0):
                raise ValueError("sharpen effect has invalid 'amount'")
            # unsharp's own luma_amount range is [-2, 5] (verified via
            # `ffmpeg -h filter=unsharp`); this effect only exposes the
            # sharpening (positive) half - matrix sizes stay at ffmpeg's own
            # 5x5 default, same one-knob curation as blur/vignette.
            parts.append(f"unsharp=luma_amount={amount}")
        elif etype == "film_grain":
            if stream != "video":
                continue
            amount = effect.get("amount", 20.0)
            if not isinstance(amount, (int, float)) or not (0.0 < amount <= 100.0):
                raise ValueError("film_grain effect has invalid 'amount'")
            # noise's alls/allf (verified via `ffmpeg -h filter=noise`):
            # allf=t+u (temporal + uniform) is what actually reads as film
            # grain - flickering per-frame, not one static dead-pixel pattern.
            parts.append(f"noise=alls={amount}:allf=t+u")
        elif etype == "glow":
            # Glow is multi-pad (split → gblur → screen blend) and cannot be
            # a single comma-chain fragment. _video_clip_chain expands it;
            # reaching here means something called _effect_filters on a glow
            # effect in isolation, which is a programming error.
            if stream != "video":
                continue
            raise NotImplementedError(
                "glow effect is multi-pad and must be expanded by _video_clip_chain, "
                "not by _effect_filters"
            )
        elif etype == "lut3d":
            if stream != "video":
                continue
            path = effect.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("lut3d effect has invalid 'path'")
            if not Path(path).exists():
                raise FileNotFoundError(f"lut3d effect path not found: {path}")
            # interp defaults to ffmpeg's own tetrahedral (best quality of the
            # options in `ffmpeg -h filter=lut3d`); path escaping reuses the
            # same Windows-verified helper textfile/fontfile already need.
            interp = effect.get("interp", "tetrahedral")
            if interp not in ("nearest", "trilinear", "tetrahedral", "pyramid", "prism"):
                raise ValueError(f"lut3d effect has invalid 'interp' {interp!r}")
            parts.append(
                f"lut3d=file='{_escape_filter_path(path)}':interp={interp}"
            )
        elif etype == "white_balance":
            if stream != "video":
                continue
            temperature = effect.get("temperature", 6500)
            mix = effect.get("mix", 1.0)
            if not isinstance(temperature, (int, float)) or not (1000 <= temperature <= 40000):
                raise ValueError("white_balance effect has invalid 'temperature'")
            if not isinstance(mix, (int, float)) or not (0.0 <= mix <= 1.0):
                raise ValueError("white_balance effect has invalid 'mix'")
            # ffmpeg colortemperature: temperature in Kelvin, mix blends the
            # filtered result with the source (1 = full effect). pl left at
            # default 0 so the grade is free to shift luminance slightly —
            # agents wanting "tint only" can lower mix instead.
            parts.append(f"colortemperature=temperature={temperature}:mix={mix}")
        elif etype == "shape_mask":
            if stream != "video":
                continue
            # Geometric alpha mask. Needs yuva + transparent pad (has_alpha).
            # geq writes the alpha plane; RGB/luma pass through (p(X,Y)).
            shape = effect.get("shape", "circle")
            if shape not in SHAPE_MASK_SHAPES:
                raise ValueError(f"shape_mask has invalid 'shape' {shape!r}")
            cx = float(effect.get("cx", 0.5))
            cy = float(effect.get("cy", 0.5))
            size = float(effect.get("size", 0.5))
            feather = float(effect.get("feather", 0.05))
            invert = bool(effect.get("invert", False))
            # geq alpha is written 0..255 into the plane (verified: a='1'
            # yields near-transparent, a='255' yields opaque). Soft edge:
            # linear ramp over feather*min(W,H) pixels.
            if shape == "circle":
                # size = radius as fraction of min(W,H)/2 so 1.0 = touch edges.
                r_expr = f"(min(W\\,H)/2)*{size}"
                dist = f"hypot(X-W*{cx}\\,Y-H*{cy})"
                if feather > 1e-6:
                    f_expr = f"(min(W\\,H)*{feather})"
                    alpha01 = f"clip(({r_expr}-({dist}))/({f_expr})\\,0\\,1)"
                else:
                    alpha01 = f"if(lte({dist}\\,{r_expr})\\,1\\,0)"
            else:  # rect
                w = float(effect.get("width", 0.5))
                h = float(effect.get("height", 0.5))
                half_w = f"(W*{w}/2)"
                half_h = f"(H*{h}/2)"
                dx = f"abs(X-W*{cx})-({half_w})"
                dy = f"abs(Y-H*{cy})-({half_h})"
                od = f"max(max({dx}\\,0)\\,max({dy}\\,0))"
                if feather > 1e-6:
                    f_expr = f"(min(W\\,H)*{feather})"
                    alpha01 = f"clip(1-({od})/({f_expr})\\,0\\,1)"
                else:
                    alpha01 = f"if(lte({od}\\,0)\\,1\\,0)"
            if invert:
                alpha01 = f"(1-({alpha01}))"
            alpha = f"255*({alpha01})"
            # Use rgba for geq so r/g/b/a expressions are unambiguous, then
            # leave yuva conversion to the pad/format step has_alpha adds.
            parts.append(
                f"format=rgba,"
                f"geq=r='r(X\\,Y)':g='g(X\\,Y)':b='b(X\\,Y)':a='{alpha}'"
            )
        elif etype == "ken_burns":
            if stream != "video":
                continue
            # True animated zoom+pan via zoompan d=1 (one out frame per in
            # frame). Root cause of the dogfood v4 / multi-clip "3141s video"
            # bomb was NOT multi-clip itself: it was chain tail
            # scale/pad/fps *after* zoompan (verified: trim+zoompan alone =
            # correct N frames; +scale/pad/fps → 15360 frames / 512s).
            # _video_clip_chain therefore skips scale/pad/fps when any
            # ken_burns is present — zoompan already emits s=box at fps.
            if out_w is None or out_h is None:
                raise RuntimeError(
                    "internal: ken_burns needs out_w/out_h from _video_clip_chain"
                )
            box_w = max(2, int(out_w) // 2 * 2)
            box_h = max(2, int(out_h) // 2 * 2)
            z0 = float(effect.get("zoom_start", 1.0))
            z1 = float(effect.get("zoom_end", 1.2))
            x0 = float(effect.get("x_start", 0.5))
            y0 = float(effect.get("y_start", 0.5))
            x1 = float(effect.get("x_end", 0.5))
            y1 = float(effect.get("y_end", 0.5))
            for name, val, lo, hi in (
                ("zoom_start", z0, 1.0, 10.0),
                ("zoom_end", z1, 1.0, 10.0),
                ("x_start", x0, 0.0, 1.0),
                ("y_start", y0, 0.0, 1.0),
                ("x_end", x1, 0.0, 1.0),
                ("y_end", y1, 0.0, 1.0),
            ):
                if not (lo <= val <= hi):
                    raise ValueError(f"ken_burns effect has invalid {name!r}")
            n_max = max(clip_duration_frames - 1, 1)
            z_expr = f"({z0})+(({z1})-({z0}))*on/{n_max}"
            fx_expr = f"({x0})+(({x1})-({x0}))*on/{n_max}"
            fy_expr = f"({y0})+(({y1})-({y0}))*on/{n_max}"
            x_expr = f"({fx_expr})*(iw-iw/zoom)"
            y_expr = f"({fy_expr})*(ih-ih/zoom)"
            parts.append(
                f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
                f"d=1:s={box_w}x{box_h}:fps={fps}"
            )
        elif etype == "compression":
            if stream != "audio":
                continue
            threshold_db = effect.get("threshold_db", -18.0)
            ratio = effect.get("ratio", 4.0)
            attack_ms = effect.get("attack_ms", 20.0)
            release_ms = effect.get("release_ms", 250.0)
            makeup_db = effect.get("makeup_db", 0.0)
            if not isinstance(ratio, (int, float)) or not (1.0 <= ratio <= 20.0):
                raise ValueError("compression effect has invalid 'ratio'")
            # acompressor's threshold/makeup are natively linear amplitude,
            # but (verified empirically - a real ffmpeg run, not assumed from
            # docs) both accept a "<n>dB" suffix same as the volume filter
            # gain's own effect already uses, so the effect's public API
            # stays dB throughout rather than mixing linear and dB knobs.
            parts.append(
                f"acompressor=threshold={threshold_db}dB:ratio={ratio}:"
                f"attack={attack_ms}:release={release_ms}:makeup={makeup_db}dB"
            )
        elif etype == "noise_reduction":
            if stream != "audio":
                continue
            amount = effect.get("amount", 12.0)
            if not isinstance(amount, (int, float)) or not (0.01 <= amount <= 97.0):
                raise ValueError("noise_reduction effect has invalid 'amount'")
            # afftdn's own nr range is [0.01, 97] dB (verified via
            # `ffmpeg -h filter=afftdn`) - single-knob curation, same as
            # every other effect here; noise_floor/noise_type stay default.
            parts.append(f"afftdn=nr={amount}")
        elif etype == "audio_eq":
            if stream != "audio":
                continue
            frequency_hz = effect.get("frequency_hz")
            gain_db = effect.get("gain_db", 0.0)
            q = effect.get("q", 1.0)
            if not isinstance(frequency_hz, (int, float)) or not (20.0 <= frequency_hz <= 20000.0):
                raise ValueError("audio_eq effect has invalid 'frequency_hz'")
            if not isinstance(gain_db, (int, float)) or not (-24.0 <= gain_db <= 24.0):
                raise ValueError("audio_eq effect has invalid 'gain_db'")
            if not isinstance(q, (int, float)) or not (0.0 < q <= 10.0):
                raise ValueError("audio_eq effect has invalid 'q'")
            # A single parametric (peaking) band - ffmpeg's own `equalizer`
            # filter, width_type=q is its own Q-factor mode (verified via
            # `ffmpeg -h filter=equalizer`). Multi-band EQ needs no separate
            # mechanism: apply_effect this multiple times at different
            # frequencies, same as any other stacked effect.
            parts.append(f"equalizer=frequency={frequency_hz}:width_type=q:width={q}:gain={gain_db}")
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


def _active_tracks(tracks: list, kind: str) -> list:
    """Apply mute/solo: if any track of kind is solo, only solos; else drop muted."""
    kind_tracks = [t for t in tracks if t.kind == kind]
    solos = [t for t in kind_tracks if getattr(t, "solo", False)]
    if solos:
        return solos
    return [t for t in kind_tracks if not getattr(t, "muted", False)]


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


def _validate_no_overlaps(track: Track) -> list:
    """Overlay video tracks (any video track after the first — see export()'s
    z-order convention) may have gaps on purpose: the layer(s) below show
    through wherever an overlay track has nothing. Clips on the *same*
    overlay track still can't overlap each other in time, though.
    """
    clips = track.clips_in_order()
    for prev, nxt in zip(clips, clips[1:]):
        if nxt.start < prev.end:
            raise ValueError(
                f"overlay track {track.id} has overlapping clips: {prev.id} "
                f"ends at frame {prev.end} but {nxt.id} starts at frame {nxt.start}"
            )
    return clips


def _video_clip_chain(
    clip: Clip, idx: int, fps: float, box_w: int, box_h: int, text_dir: Path, label: str
) -> str:
    """The trim -> speed -> effects -> scale/pad chain for one clip's video
    stream. Shared by the base track and overlay layers — a clip gets the
    same treatment either way, just against a different target box size
    (``box_w``/``box_h``): the full canvas for the base track and
    non-positioned overlay clips, or a smaller picture-in-picture box for an
    overlay clip with ``position`` set (see Clip.position, export()).

    Most effects are linear filter fragments (comma-joined). ``glow`` is the
    exception: it needs split → blur → screen-blend (multi-pad), so this
    function returns one or more filtergraph statements joined by ``;`` when
    any glow is present. Callers already ``";".join`` clip chains, so an
    embedded ``;`` is fine.
    """
    speed_pts = _speed_filter(clip.speed, "video") or "setpts=PTS-STARTPTS"
    effects = list(clip.effects or [])
    if getattr(clip, "muted", False):
        # Black out while keeping duration/contiguity
        effects = effects + [
            {"type": "color", "brightness": -1.0, "contrast": 1.0, "saturation": 0.0},
        ]
    has_alpha = any(
        e.get("type") in ("chroma_key", "luma_key", "shape_mask") for e in effects
    )
    # ken_burns (zoompan) already emits exactly box_w x box_h at project fps.
    # Appending the normal scale/pad/fps tail after zoompan multiplies frame
    # count into the thousands (spike: 30 → 15360). Skip size/fps tail when
    # present; keep setsar (+ alpha format if needed).
    has_ken_burns = any(e.get("type") == "ken_burns" for e in effects)
    pad_color = "black@0.0" if has_alpha else "black"
    if has_ken_burns:
        tail_filters = []
        if has_alpha:
            tail_filters.append("format=yuva420p")
        tail_filters.append("setsar=1")
    else:
        tail_filters = [
            f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease",
            f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color={pad_color}",
        ]
        if has_alpha:
            tail_filters.append("format=yuva420p")
        tail_filters.append("setsar=1")
        tail_filters.append(f"fps={fps}")

    # Partition effects into linear runs separated by glow barriers.
    # Linear runs still go through _effect_filters; glow expands here.
    segments: list[tuple[str, Any]] = []
    linear_batch: list[dict[str, Any]] = []
    for effect in effects:
        if effect.get("type") == "glow":
            if linear_batch:
                segments.append(("linear", linear_batch))
                linear_batch = []
            segments.append(("glow", effect))
        else:
            linear_batch.append(effect)
    if linear_batch:
        segments.append(("linear", linear_batch))

    has_glow = any(kind == "glow" for kind, _ in segments)
    if not has_glow:
        fx = _effect_filters(
            effects, clip.timeline_duration_frames, fps, "video", text_dir,
            out_w=box_w, out_h=box_h,
        )
        chain = f"[{idx}:v]trim=start_frame={clip.src_in}:end_frame={clip.src_out},{speed_pts}"
        for filt in fx:
            chain += f",{filt}"
        chain += "," + ",".join(tail_filters) + f"[{label}]"
        return chain

    # Multi-pad path: glow needs RGB (gbrp) for screen blend — verified
    # spike: screen-blending in yuv420p produced purple-tinted garbage;
    # format=gbrp before split/blur/blend keeps the halo neutral and the
    # far-field pure black.
    statements: list[str] = []
    mid_n = 0

    def _mid() -> str:
        nonlocal mid_n
        mid_n += 1
        # label is already unique per clip in the export graph (e.g. v0c0);
        # suffix keeps intermediate pads from colliding across glows.
        return f"{label}_g{mid_n}"

    # Start: trim + speed into the first mid label, then walk segments.
    head = f"[{idx}:v]trim=start_frame={clip.src_in}:end_frame={clip.src_out},{speed_pts}"
    current_src: str | None = None  # None → still on the head chain

    def _flush_linear(filters: list[str], out_label: str) -> None:
        nonlocal current_src, head
        if current_src is None:
            body = head
            if filters:
                body += "," + ",".join(filters)
            statements.append(f"{body}[{out_label}]")
        else:
            if filters:
                statements.append(f"[{current_src}]" + ",".join(filters) + f"[{out_label}]")
            else:
                # No-op passthrough — just reuse the label.
                statements.append(f"[{current_src}]null[{out_label}]")
        current_src = out_label

    for kind, payload in segments:
        if kind == "linear":
            frags = _effect_filters(
                payload, clip.timeline_duration_frames, fps, "video", text_dir,
                out_w=box_w, out_h=box_h,
            )
            if not frags and current_src is not None:
                continue
            out = _mid()
            _flush_linear(frags, out)
        else:
            # glow: flush any pending head into a label first
            if current_src is None:
                out = _mid()
                _flush_linear([], out)
            amount = payload.get("amount", 12.0)
            intensity = payload.get("intensity", 0.7)
            if not isinstance(amount, (int, float)) or not (0.0 < amount <= 50.0):
                raise ValueError("glow effect has invalid 'amount'")
            if not isinstance(intensity, (int, float)) or not (0.0 < intensity <= 1.0):
                raise ValueError("glow effect has invalid 'intensity'")
            base_l, tmp_l, blur_l, out_l = _mid(), _mid(), _mid(), _mid()
            # Convert to RGB *before* split so both legs agree on colorspace.
            statements.append(f"[{current_src}]format=gbrp,split[{base_l}][{tmp_l}]")
            statements.append(f"[{tmp_l}]gblur=sigma={amount}[{blur_l}]")
            statements.append(
                f"[{base_l}][{blur_l}]blend=all_mode=screen:all_opacity={intensity}[{out_l}]"
            )
            current_src = out_l

    # Tail: scale/pad/fps onto the final output label.
    assert current_src is not None
    statements.append(
        f"[{current_src}]" + ",".join(tail_filters) + f"[{label}]"
    )
    return ";".join(statements)


def _audio_clip_chain(clip: Clip, idx: int, tb, sample_rate: int, label: str) -> str:
    """The atrim -> speed -> effects -> resample/format chain for one clip's
    audio stream. Ends in an explicit aformat (float stereo): every audio
    label downstream feeds concat/acrossfade/amix/sidechaincompress, all of
    which need their inputs to agree on format — normalising here once beats
    letting a mono voiceover meet a stereo music bed inside amix."""
    fps = tb.fps
    effects = list(clip.effects or [])
    if getattr(clip, "muted", False):
        effects = effects + [{"type": "gain", "db": -100.0}]
    fx = _effect_filters(effects, clip.timeline_duration_frames, fps, "audio")
    chain = (
        f"[{idx}:a]atrim=start={tb.frames_to_seconds(clip.src_in):.6f}:"
        f"end={tb.frames_to_seconds(clip.src_out):.6f},asetpts=PTS-STARTPTS"
    )
    speed_tempo = _speed_filter(clip.speed, "audio")
    if speed_tempo:
        chain += f",{speed_tempo}"
    for filt in fx:
        chain += f",{filt}"
    chain += (
        f",aresample={sample_rate},"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo[{label}]"
    )
    return chain


def _overlay_box(clip: Clip, W: int, H: int) -> tuple[int, int, int, int]:
    """(box_w, box_h, x_px, y_px) for one overlay clip: full canvas at (0, 0)
    if ``clip.position`` is unset, else a scaled-down box placed per
    Editor.set_position's x/y-as-fraction-of-available-room convention."""
    pos = clip.position
    if pos is None:
        return W, H, 0, 0
    scale = pos["scale"]
    # yuv420p (chroma subsampling) requires even width/height - an odd box
    # size (e.g. scale=0.5 on a 90px-tall canvas -> 45) breaks pad/encode
    # with an opaque "Padded dimensions cannot be smaller than input
    # dimensions" error, verified empirically. Round down to even, floor 2.
    box_w = max(2, round(W * scale)) // 2 * 2
    box_h = max(2, round(H * scale)) // 2 * 2
    x_px = round(pos["x"] * (W - box_w))
    y_px = round(pos["y"] * (H - box_h))
    return box_w, box_h, x_px, y_px


def _track_all_media_have_audio(project: Project, track: Track) -> bool:
    return bool(track.clips) and all(
        project.media_by_id(c.media).has_audio for c in track.clips
    )


# Opmiere transition_type -> ffmpeg xfade's own `transition` option (verified
# via `ffmpeg -h filter=xfade`: 57 real values exist, this is the curated
# subset model.KNOWN_TRANSITION_TYPES actually exposes - not guessed names).
_XFADE_TRANSITION_BY_TYPE = {
    "cross_dissolve": "fade",
    "dip_to_black": "fadeblack",
    "dip_to_white": "fadewhite",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
}


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
                xfade_name = _XFADE_TRANSITION_BY_TYPE[transition["type"]]
                parts.append(
                    f"[{running}][{labels[i]}]xfade=transition={xfade_name}:"
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
    def __init__(self, *, prefer_nvenc: bool = True):
        self.prefer_nvenc = prefer_nvenc

    def export(self, project: Project, bundle: Bundle, output_path: Path) -> Path:
        require_ffmpeg_tools()
        output_path = Path(output_path)

        # z-order convention: the first video track on the project is the
        # base/background layer (rendered exactly as P0 always has); any
        # video tracks after it are overlay layers, stacked in list order,
        # each full-frame and active only during its own clips' windows —
        # see _video_clip_chain/_validate_no_overlaps and the overlay loop
        # below. Nothing about Editor/model changed for this: it never
        # restricted track counts, only this backend did.
        video_tracks = _active_tracks(project.tracks, "video")
        audio_tracks = _active_tracks(project.tracks, "audio")
        base_video_track = video_tracks[0] if video_tracks else None
        overlay_video_tracks = video_tracks[1:]
        base_audio_track = audio_tracks[0] if audio_tracks else None
        overlay_audio_tracks = audio_tracks[1:]
        if base_video_track is None and base_audio_track is None:
            raise ValueError(
                "project has no audible/visible tracks to render "
                "(all muted? clear mute or enable solo)"
            )

        base_video_clips = _validate_contiguous(base_video_track) if base_video_track else []
        overlay_clips_by_track = [_validate_no_overlaps(t) for t in overlay_video_tracks]
        # Empty base audio is allowed (detach_audio places free-timed clips on
        # later overlay audio tracks and must not re-use embedded video audio).
        any_audio_clips = any(t.clips for t in audio_tracks)
        if base_audio_track and base_audio_track.clips:
            _validate_contiguous(base_audio_track)
            audio_source_track = base_audio_track
        else:
            audio_source_track = None
        # Overlay audio tracks may have gaps (a voiceover line here, an SFX
        # there); an empty overlay track simply contributes nothing.
        overlay_audio_clips_by_track = [_validate_no_overlaps(t) for t in overlay_audio_tracks]

        # Fall back to base video embedded audio only when *no* audio-track
        # clips exist (otherwise detach_audio / music beds would double-mix).
        if audio_source_track is None and base_video_track is not None and not any_audio_clips:
            audio_source_track = (
                base_video_track if _track_all_media_have_audio(project, base_video_track) else None
            )

        # One -i per unique media file, in order of first appearance.
        media_order: list[str] = []
        seen: set[str] = set()
        for track in (base_video_track, *overlay_video_tracks, audio_source_track, *overlay_audio_tracks):
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
            if base_video_track is not None:
                for n, clip in enumerate(base_video_clips):
                    idx = media_index[clip.media]
                    label = f"v{n}"
                    filter_parts.append(_video_clip_chain(clip, idx, fps, W, H, text_dir, label))
                    vlabels.append(label)
                if len(vlabels) == 1:
                    video_final_label = vlabels[0]
                else:
                    filter_parts.extend(_fold_segments(vlabels, base_video_clips, fps, "video", "vout"))
                    video_final_label = "vout"

                # Overlay layers, stacked in track order. Each clip gets its
                # own full-frame chain, then an `overlay` step with an
                # `enable` window - outside that window the composite so far
                # passes through untouched, which is what lets overlay
                # tracks have gaps (no chroma-key/alpha needed for this).
                tb = project.timebase
                overlay_n = 0
                for track_clips in overlay_clips_by_track:
                    for clip in track_clips:
                        idx = media_index[clip.media]
                        src_label = f"ov{overlay_n}"
                        box_w, box_h, x_px, y_px = _overlay_box(clip, W, H)
                        filter_parts.append(
                            _video_clip_chain(clip, idx, fps, box_w, box_h, text_dir, src_label)
                        )
                        start_s = tb.frames_to_seconds(clip.start)
                        end_s = tb.frames_to_seconds(clip.end)
                        out_label = f"vcomp{overlay_n}"
                        filter_parts.append(
                            f"[{video_final_label}][{src_label}]overlay=x={x_px}:y={y_px}:"
                            f"enable='between(t,{start_s:.6f},{end_s:.6f})'[{out_label}]"
                        )
                        video_final_label = out_label
                        overlay_n += 1

            audio_final_label: str | None = None
            sample_rate = project.timebase.sample_rate
            tb = project.timebase
            # track.id -> its submix's current filter label, in mix order.
            audio_track_labels: dict[str, str] = {}
            mix_order: list[str] = []

            if audio_source_track is not None:
                audio_clips = audio_source_track.clips_in_order()
                alabels: list[str] = []
                for n, clip in enumerate(audio_clips):
                    filter_parts.append(
                        _audio_clip_chain(clip, media_index[clip.media], tb, sample_rate, f"a{n}")
                    )
                    alabels.append(f"a{n}")
                if len(alabels) == 1:
                    base_label = alabels[0]
                else:
                    filter_parts.extend(_fold_segments(alabels, audio_clips, fps, "audio", "abase"))
                    base_label = "abase"
                audio_track_labels[audio_source_track.id] = base_label
                mix_order.append(audio_source_track.id)

            for j, (track, track_clips) in enumerate(
                zip(overlay_audio_tracks, overlay_audio_clips_by_track)
            ):
                if not track_clips:
                    continue
                seg_labels: list[str] = []
                for n, clip in enumerate(track_clips):
                    label = f"ao{j}_{n}"
                    filter_parts.append(
                        _audio_clip_chain(clip, media_index[clip.media], tb, sample_rate, label)
                    )
                    if clip.start > 0:
                        delay_ms = round(tb.frames_to_seconds(clip.start) * 1000)
                        filter_parts.append(f"[{label}]adelay=delays={delay_ms}:all=1[{label}d]")
                        label = f"{label}d"
                    seg_labels.append(label)
                if len(seg_labels) == 1:
                    track_label = seg_labels[0]
                else:
                    # Within one overlay track the (validated non-overlapping,
                    # individually delayed) clips just sum; normalize=0 keeps
                    # each at its authored level instead of amix's default
                    # 1/N scaling.
                    track_label = f"atrk{j}"
                    filter_parts.append(
                        "".join(f"[{s}]" for s in seg_labels)
                        + f"amix=inputs={len(seg_labels)}:duration=longest:normalize=0[{track_label}]"
                    )
                audio_track_labels[track.id] = track_label
                mix_order.append(track.id)

            # Ducking (model.Track.duck): split every key track's *pre-duck*
            # submix first, then apply each sidechaincompress — pre-duck keys
            # are what make mutual ducking acyclic by construction.
            ducked_tracks = []
            key_counts: dict[str, int] = {}
            for track in audio_tracks:
                if track.duck is None or track.id not in audio_track_labels:
                    continue
                against_id = track.duck["against"]
                if against_id not in audio_track_labels:
                    raise ValueError(
                        f"track {track.id} ducks against {against_id}, which has "
                        "no rendered audio (track missing or empty) — clear_ducking "
                        "or give the key track clips"
                    )
                key_counts[against_id] = key_counts.get(against_id, 0) + 1
                ducked_tracks.append(track)

            key_labels: dict[str, list[str]] = {}
            for against_id, count in key_counts.items():
                src = audio_track_labels[against_id]
                keys = [f"{src}k{i}" for i in range(count)]
                filter_parts.append(
                    f"[{src}]asplit={count + 1}[{src}m]" + "".join(f"[{k}]" for k in keys)
                )
                audio_track_labels[against_id] = f"{src}m"
                key_labels[against_id] = keys

            for track in ducked_tracks:
                duck = track.duck
                key = key_labels[duck["against"]].pop()
                src = audio_track_labels[track.id]
                # apad the key: sidechaincompress ends at its *shortest* input
                # (verified empirically — an unpadded 1s key truncated a 4s
                # main to 1s), so a key shorter than the ducked track would
                # otherwise cut the mix off. Padding with silence is also the
                # right semantics (no key signal = no ducking), and the main
                # input still bounds the output length.
                filter_parts.append(f"[{key}]apad[{key}p]")
                filter_parts.append(
                    f"[{src}][{key}p]sidechaincompress="
                    f"threshold={duck['threshold_db']}dB:ratio={duck['ratio']}:"
                    f"attack={duck['attack_ms']}:release={duck['release_ms']}:"
                    f"makeup={duck['makeup_db']}dB[{src}duck]"
                )
                audio_track_labels[track.id] = f"{src}duck"

            final_labels = [audio_track_labels[track_id] for track_id in mix_order]
            if len(final_labels) == 1:
                audio_final_label = final_labels[0]
            elif final_labels:
                filter_parts.append(
                    "".join(f"[{s}]" for s in final_labels)
                    + f"amix=inputs={len(final_labels)}:duration=longest:normalize=0[aout]"
                )
                audio_final_label = "aout"

            filter_complex = ";".join(filter_parts)

            hw_in = hwaccel_input_args(prefer_cuda=self.prefer_nvenc)
            # hwaccel before each -i is invalid; global before first -i
            cmd = ["ffmpeg", "-y", *hw_in, *input_args, "-filter_complex", filter_complex]
            if video_final_label:
                venc = video_encode_args(prefer_nvenc=self.prefer_nvenc)
                # video_encode_args already includes -pix_fmt
                cmd += ["-map", f"[{video_final_label}]", *venc]
            if audio_final_label:
                cmd += ["-map", f"[{audio_final_label}]", "-c:a", "aac"]
            else:
                cmd += ["-an"]
            cmd += [str(output_path)]

            proc = subprocess.run(cmd, capture_output=True, text=True)
            # If NVENC path failed, one retry with pure software
            if proc.returncode != 0 and self.prefer_nvenc and video_final_label:
                cmd_sw = [
                    "ffmpeg", "-y", *input_args,
                    "-filter_complex", filter_complex,
                    "-map", f"[{video_final_label}]",
                    *video_encode_args(prefer_nvenc=False),
                ]
                if audio_final_label:
                    cmd_sw += ["-map", f"[{audio_final_label}]", "-c:a", "aac"]
                else:
                    cmd_sw += ["-an"]
                cmd_sw += [str(output_path)]
                proc2 = subprocess.run(cmd_sw, capture_output=True, text=True)
                if proc2.returncode == 0:
                    proc = proc2
                else:
                    proc = proc  # keep first error context
            if proc.returncode != 0:
                raise RuntimeError(
                    "ffmpeg export failed (exit "
                    f"{proc.returncode}):\ncmd: {' '.join(cmd)}\nstderr:\n{proc.stderr}"
                )
        return output_path


FIT_MODES = frozenset({"none", "contain", "cover"})


def _fps_mismatch(src_fps: float | None, project_fps: float) -> bool:
    if src_fps is None or src_fps <= 0:
        return True
    return abs(float(src_fps) - float(project_fps)) > 0.05


def _size_mismatch(
    width: int | None,
    height: int | None,
    project_w: int,
    project_h: int,
) -> bool:
    if not width or not height:
        return True
    return abs(int(width) - int(project_w)) > 8 or abs(int(height) - int(project_h)) > 8


def _build_video_filter(
    *,
    project_fps: float,
    fit: str,
    project_w: int,
    project_h: int,
    force_fps: bool,
) -> str:
    """Compose fps + optional scale/pad/crop chain."""
    parts: list[str] = []
    if force_fps:
        parts.append(f"fps={project_fps}")
    if fit == "contain":
        # letterbox / pillarbox to exact canvas
        parts.append(
            f"scale={project_w}:{project_h}:force_original_aspect_ratio=decrease"
        )
        parts.append(
            f"pad={project_w}:{project_h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        parts.append("setsar=1")
    elif fit == "cover":
        # fill canvas, center-crop overflow
        parts.append(
            f"scale={project_w}:{project_h}:force_original_aspect_ratio=increase"
        )
        parts.append(f"crop={project_w}:{project_h}")
        parts.append("setsar=1")
    if not parts:
        # fps already matching and fit=none — caller should not re-encode
        parts.append(f"fps={project_fps}")
    return ",".join(parts)


def conform_to_project_timebase(
    src_path: Path,
    dest_path: Path,
    *,
    project_fps: float,
    sample_rate: int = 48000,
    has_video: bool,
    has_audio: bool,
    fit: str = "none",
    project_w: int | None = None,
    project_h: int | None = None,
    force_fps: bool = True,
) -> dict[str, Any]:
    """Re-encode ``src_path`` to project fps and optional canvas fit.

    fit: none | contain (letterbox) | cover (crop-fill).
    """
    if fit not in FIT_MODES:
        raise ValueError(f"fit must be one of {sorted(FIT_MODES)}, got {fit!r}")
    require_ffmpeg_tools()
    src_path = Path(src_path)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-i", str(src_path)]
    if has_video:
        w = int(project_w or 1920)
        h = int(project_h or 1080)
        vf = _build_video_filter(
            project_fps=project_fps,
            fit=fit,
            project_w=w,
            project_h=h,
            force_fps=force_fps or fit != "none",
        )
        cmd += [
            "-vf", vf,
            "-r", str(project_fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "18",
        ]
    else:
        cmd += ["-vn"]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", str(sample_rate), "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd.append(str(dest_path))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest_path.exists():
        raise RuntimeError(
            f"fps/fit conform failed for {src_path}:\n"
            f"{(proc.stderr or '')[-2500:]}"
        )
    return {
        "path": str(dest_path),
        "project_fps": project_fps,
        "sample_rate": sample_rate,
        "has_video": has_video,
        "has_audio": has_audio,
        "fit": fit,
        "project_w": project_w,
        "project_h": project_h,
        "force_fps": force_fps,
    }


def import_media(
    bundle: Bundle,
    project: Project,
    src_path: Path,
    kind: MediaKind,
    dest_name: str | None = None,
    origin: dict[str, Any] | None = None,
    *,
    conform: bool = True,
    fit: str = "none",
) -> Media:
    """Copy ``src_path`` into the bundle and register it on the project.

    For kind="video"/"audio", fields come from ffprobe (never guessed).

    conform=True (default): when video fps ≠ project timebase, re-encode to
    project fps so P0 frame-trim export works.

    fit:
      - none (default): keep source pixel size (export scales/pads later)
      - contain: letterbox into project resolution
      - cover: crop-fill into project resolution
    Any non-none fit triggers a re-encode when size or fps needs alignment.

    kind="image" uses IMAGE_VIRTUAL_DURATION_FRAMES (see model.py).
    ``origin["conformed"]`` records auto re-encode details when applied.
    """
    if fit not in FIT_MODES:
        raise ValueError(f"fit must be one of {sorted(FIT_MODES)}, got {fit!r}")
    require_ffmpeg_tools()
    src_path = Path(src_path)

    if kind == "image":
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        # Optional: stills can be scaled into a short video for fit — keep
        # still as image media; export path already scales images.
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
    origin_out: dict[str, Any] | None = dict(origin) if origin else None

    if kind == "video":
        if not result.has_video:
            raise ValueError(
                f"{src_path} has no video stream; cannot import as kind='video'"
            )
        src_fps = float(result.fps or 0.0)
        src_w, src_h = result.width, result.height
        need_fps = _fps_mismatch(src_fps, project.timebase.fps)
        need_size = fit != "none" and _size_mismatch(
            src_w, src_h, project.resolution.w, project.resolution.h,
        )
        # Explicit fit on already-matching canvas still forces re-encode so
        # agents can "normalize all clips to project pixels" predictably.
        force_fit = fit != "none"
        need_reencode = need_fps or need_size or force_fit

        if need_fps and not conform and not force_fit:
            raise ValueError(
                f"source fps {src_fps:.3f} does not match project "
                f"fps {project.timebase.fps:.3f} ({src_path}). "
                "Pass conform=True (default) to re-encode, or match fps."
            )
        if need_reencode and (conform or force_fit):
            stem = src_path.stem.replace(" ", "_")[:40]
            tag = f"f{int(round(project.timebase.fps))}"
            if force_fit:
                tag += f"_{fit}"
            conf_name = dest_name or f"{stem}_{tag}_{uuid.uuid4().hex[:6]}.mp4"
            if not conf_name.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                conf_name = conf_name + ".mp4"
            dest = bundle.media_dir / conf_name
            if dest.exists():
                dest = bundle.media_dir / f"{stem}_{uuid.uuid4().hex[:8]}.mp4"
            applied_fit = fit if force_fit else "none"
            conf_report = conform_to_project_timebase(
                src_path,
                dest,
                project_fps=project.timebase.fps,
                sample_rate=project.timebase.sample_rate,
                has_video=True,
                has_audio=result.has_audio,
                fit=applied_fit,
                project_w=project.resolution.w,
                project_h=project.resolution.h,
                force_fps=True,
            )
            after = probe(dest)
            origin_out = origin_out or {}
            origin_out["conformed"] = {
                "from_fps": src_fps,
                "to_fps": project.timebase.fps,
                "from_size": {"width": src_w, "height": src_h},
                "to_size": {"width": after.width, "height": after.height},
                "fit": applied_fit,
                "source_path": str(src_path.resolve()),
                **{k: v for k, v in conf_report.items() if k != "path"},
            }
            duration_frames = project.timebase.seconds_to_frames(
                after.duration_seconds
            )
            rel_path = dest.relative_to(bundle.media_dir).as_posix()
            return project.add_media(
                kind=kind,
                path=rel_path,
                duration_frames=duration_frames,
                has_audio=after.has_audio,
                origin=origin_out,
            )
        if need_fps and not conform:
            raise ValueError(
                f"source fps {src_fps:.3f} does not match project "
                f"fps {project.timebase.fps:.3f} ({src_path})"
            )
    elif kind == "audio":
        if not result.has_audio:
            raise ValueError(
                f"{src_path} has no audio stream; cannot import as kind='audio' "
                f"(file may be video-only or corrupt)"
            )
        # Resample to project sample_rate when far from timebase (mix safety)
        src_sr = result.sample_rate
        proj_sr = int(project.timebase.sample_rate)
        if (
            conform
            and src_sr is not None
            and abs(int(src_sr) - proj_sr) > 50
        ):
            stem = src_path.stem.replace(" ", "_")[:40]
            conf_name = dest_name or f"{stem}_sr{proj_sr}_{uuid.uuid4().hex[:6]}.m4a"
            if not conf_name.lower().endswith((".m4a", ".wav", ".mp3", ".aac", ".flac")):
                conf_name = conf_name + ".m4a"
            dest = bundle.media_dir / conf_name
            if dest.exists():
                dest = bundle.media_dir / f"{stem}_{uuid.uuid4().hex[:8]}.m4a"
            conf_report = conform_to_project_timebase(
                src_path,
                dest,
                project_fps=project.timebase.fps,
                sample_rate=proj_sr,
                has_video=False,
                has_audio=True,
                fit="none",
                force_fps=False,
            )
            after = probe(dest)
            origin_out = origin_out or {}
            origin_out["conformed"] = {
                "from_sample_rate": src_sr,
                "to_sample_rate": proj_sr,
                "source_path": str(src_path.resolve()),
                **{k: v for k, v in conf_report.items() if k != "path"},
            }
            duration_frames = project.timebase.seconds_to_frames(
                after.duration_seconds
            )
            rel_path = dest.relative_to(bundle.media_dir).as_posix()
            return project.add_media(
                kind=kind,
                path=rel_path,
                duration_frames=duration_frames,
                has_audio=True,
                origin=origin_out,
            )
    else:
        raise ValueError(
            f"unknown media kind {kind!r}; use video, audio, or image"
        )

    if not src_path.exists():
        raise FileNotFoundError(
            f"cannot import — file not found: {src_path}"
        )
    dest = bundle.import_file(src_path, dest_name=dest_name)
    duration_frames = project.timebase.seconds_to_frames(result.duration_seconds)
    rel_path = dest.relative_to(bundle.media_dir).as_posix()
    return project.add_media(
        kind=kind,
        path=rel_path,
        duration_frames=duration_frames,
        has_audio=result.has_audio,
        origin=origin_out,
    )
