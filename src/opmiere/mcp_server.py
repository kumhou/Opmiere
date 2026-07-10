"""Opmiere MCP server — the agent-facing projection of the Operation API (ops.py).

ARCHITECTURE.md section 5.5: a thin adapter over Editor. Every tool here is a
near-mechanical wrapper around an Editor method (section 7's design goal: "MCP
tools are a near-mechanical projection of this list"). No editing logic lives
here — only argument marshalling and JSON-friendly serialisation.

Run standalone for local testing:  python -m opmiere.mcp_server
Point an MCP client (Claude Desktop, Cursor, Claude Code) at this module via
stdio to drive Opmiere with no GUI.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .director_policy import get_policy as _get_director_policy
from .generation import ComfyUIProvider
from .model import MediaKind, TrackKind
from .ops import Editor
from .render.probe import probe as _probe
from .workflow import (
    get_workflow as _get_film_workflow,
    make_brief as _make_director_brief,
    plan_session as _plan_director_session,
    validate_brief as _validate_director_brief,
)

mcp = FastMCP(
    name="opmiere",
    instructions=(
        "Opmiere is an agent-native video editor. For a full cut from user "
        "materials + intent: get_film_workflow → make_director_brief → "
        "plan_director_session, then execute the plan's tools in order. "
        "Call create_project or open_project first. get_project_state shows "
        "the timeline (ids). Positions/trims are frames at project fps. "
        "Prefer place_from_file for user assets; generate only gaps. "
        "Per fragment: get_director_policy gates — generate → job_status → "
        "quality_check → make_contact_sheet → place_generated/upscale/redo. "
        "Prefer deterministic apply_effect over re-generate for grade/timing."
    ),
)

_editor: Editor | None = None
_generation_provider: ComfyUIProvider | None = None


def _require_editor() -> Editor:
    if _editor is None:
        raise RuntimeError("no project is open — call create_project or open_project first")
    return _editor


def _get_generation_provider() -> ComfyUIProvider:
    # One provider instance per server process, reused across projects - it
    # holds no per-project state, just where to reach the (also persistent)
    # local ComfyUI server.
    global _generation_provider
    if _generation_provider is None:
        _generation_provider = ComfyUIProvider()
    return _generation_provider


@mcp.tool()
def create_project(
    bundle_path: str, fps: float = 30.0, width: int = 1920, height: int = 1080
) -> dict:
    """Create a new .opm project bundle and make it the active project."""
    global _editor
    _editor = Editor.create(
        Path(bundle_path), fps=fps, width=width, height=height,
        generation_provider=_get_generation_provider(),
    )
    return _editor.describe()


@mcp.tool()
def open_project(bundle_path: str) -> dict:
    """Open an existing .opm project bundle and make it the active project."""
    global _editor
    _editor = Editor.open(Path(bundle_path), generation_provider=_get_generation_provider())
    return _editor.describe()


@mcp.tool()
def get_project_state() -> dict:
    """Return the full current project: timebase, resolution, media, tracks, clips."""
    return _require_editor().describe()


@mcp.tool()
def get_timeline_view() -> dict:
    """Proportional timeline layout: clip seconds, labels, proxy/undo flags.

    Prefer for scrub UI / layout; get_project_state remains the full model dump.
    """
    return _require_editor().timeline_view()


@mcp.tool()
def import_media(
    src_path: str,
    kind: MediaKind,
    conform: bool = True,
    fit: str = "none",
    build_proxy: bool = False,
    proxy_height: int = 480,
) -> dict:
    """Copy a source file into the project and register it as media.

    kind: video | audio | image.
    conform=true: re-encode when source fps ≠ project timebase.
    fit: none | contain (letterbox to project WxH) | cover (crop-fill).
    build_proxy=true: also build a low-res asset proxy under proxies/.
    origin.conformed records from/to fps and size when re-encoded.
    """
    media = _require_editor().import_media(
        Path(src_path),
        kind,
        conform=conform,
        fit=fit,
        build_proxy=build_proxy,
        proxy_height=proxy_height,
    )
    return media.to_dict()


@mcp.tool()
def list_media_bin() -> dict:
    """Media bin: sources, per-asset proxy readiness, transcript cache flags."""
    return _require_editor().list_media_bin()


@mcp.tool()
def ensure_media_proxy(
    media_id: str,
    height: int = 480,
    force: bool = False,
) -> dict:
    """Build or reuse a low-res proxy for one media asset (bin scrub, not delivery)."""
    return _require_editor().ensure_media_proxy(
        media_id, height=height, force=force,
    )


@mcp.tool()
def ensure_all_media_proxies(
    height: int = 480,
    force: bool = False,
) -> dict:
    """Build missing proxies for all video media in the project."""
    return _require_editor().ensure_all_media_proxies(height=height, force=force)


@mcp.tool()
def add_track(kind: TrackKind) -> dict:
    """Add a new track ('video' or 'audio') to the timeline.

    Tracks of a kind stack by creation order, video and audio alike: the
    *first* track of a kind is the base layer (clips must be contiguous from
    frame 0), and every one added after it is an overlay layer that allows
    gaps and doesn't need to start at frame 0 (clips on the same overlay
    track still can't overlap each other).

    Video: overlays composite over the base, full-frame, during their own
    clips' [start, end) windows - the base (or lower overlays) show through
    elsewhere. See set_position for picture-in-picture sizing and the
    "chroma_key" effect for transparency.

    Audio: every audio track plays at once, mixed together - e.g. a music
    bed on the first audio track, voiceover lines placed at any frame on a
    second, SFX on a third. Levels are preserved as authored (no automatic
    re-balancing): use the "gain" effect per clip to balance the mix, and
    set_ducking to automatically dip one track under another.
    """
    return _require_editor().add_track(kind).to_dict()


@mcp.tool()
def delete_track(track_id: str) -> dict:
    """Remove a track and every clip on it. Any other track that was ducking
    against it has its ducking cleared too (rather than leaving a broken
    reference that would fail every later export). Undoable."""
    return _require_editor().delete_track(track_id).to_dict()


@mcp.tool()
def add_clip(track_id: str, media_id: str, start: int, src_in: int, src_out: int) -> dict:
    """Place the trimmed range [src_in, src_out) of media_id onto track_id at frame `start`."""
    return _require_editor().add_clip(track_id, media_id, start, src_in, src_out).to_dict()


@mcp.tool()
def place_from_file(
    src_path: str,
    kind: MediaKind,
    track_id: str,
    start: int,
    duration_frames: int | None = None,
    origin: dict | None = None,
    conform: bool = True,
    fit: str = "none",
) -> dict:
    """Import a local file and place it on a track in one step (one undo).

    kind: video | audio | image. Omit duration_frames for full file length
    (required for image). conform/fit same as import_media.
    """
    return (
        _require_editor()
        .place_from_file(
            Path(src_path), kind, track_id, start, duration_frames,
            origin=origin, conform=conform, fit=fit,
        )
        .to_dict()
    )


@mcp.tool()
def move_clip(clip_id: str, new_start: int) -> dict:
    """Move a clip to a new timeline start frame."""
    return _require_editor().move_clip(clip_id, new_start).to_dict()


@mcp.tool()
def trim_clip(clip_id: str, src_in: int, src_out: int) -> dict:
    """Change a clip's source in/out trim points (frames)."""
    return _require_editor().trim_clip(clip_id, src_in, src_out).to_dict()


@mcp.tool()
def split_clip(clip_id: str, at_frame: int) -> dict:
    """Split a clip at an absolute timeline frame into two clips."""
    first, second = _require_editor().split_clip(clip_id, at_frame)
    return {"first": first.to_dict(), "second": second.to_dict()}


@mcp.tool()
def delete_clip(clip_id: str) -> dict:
    """Remove a clip from its track (leaves a hole — use ripple_delete to close)."""
    return _require_editor().delete_clip(clip_id).to_dict()


@mcp.tool()
def ripple_delete(clip_id: str) -> dict:
    """Delete a clip and pull later clips on the same track left to close the gap."""
    return _require_editor().ripple_delete(clip_id)


@mcp.tool()
def close_gaps(track_id: str, from_frame: int = 0) -> dict:
    """Pack clips on a track contiguous from from_frame (clears transitions)."""
    return _require_editor().close_gaps(track_id, from_frame=from_frame)


@mcp.tool()
def detach_audio(
    clip_id: str,
    audio_track_id: str | None = None,
    audio_start_offset_frames: int = 0,
) -> dict:
    """Split picture/sound: copy clip audio to an audio track for J/L timing.

    audio_start_offset_frames: negative = audio leads (J-cut), positive = lags.
    While any audio-track clips exist, embedded video audio is not mixed.
    """
    return _require_editor().detach_audio(
        clip_id,
        audio_track_id,
        audio_start_offset_frames=audio_start_offset_frames,
    )


@mcp.tool()
def slip_clip(clip_id: str, delta_src_frames: int) -> dict:
    """Slip: move source in/out together; timeline start and duration stay put.

    Positive = later material in the file. Clamped to media bounds. speed=1 only.
    """
    return _require_editor().slip_clip(clip_id, delta_src_frames)


@mcp.tool()
def roll_edit(left_clip_id: str, right_clip_id: str, delta_frames: int) -> dict:
    """Roll the hard-cut between two adjacent clips (pair length unchanged).

    Positive: cut moves later (left longer, right shorter at the head).
    """
    return _require_editor().roll_edit(left_clip_id, right_clip_id, delta_frames)


@mcp.tool()
def slide_clip(clip_id: str, delta_frames: int) -> dict:
    """Slide a middle clip; neighbors absorb so A–B–C block length is constant.

    Needs prev+next hard-cut neighbors. Positive = later on the timeline.
    """
    return _require_editor().slide_clip(clip_id, delta_frames)


@mcp.tool()
def ripple_trim(
    clip_id: str,
    new_src_in: int | None = None,
    new_src_out: int | None = None,
) -> dict:
    """Trim a clip's source range and ripple later clips to keep contiguity."""
    return _require_editor().ripple_trim(
        clip_id, new_src_in=new_src_in, new_src_out=new_src_out,
    )


@mcp.tool()
def export_range(
    output_path: str,
    start_seconds: float,
    end_seconds: float,
    normalize_preset: str | None = None,
    run_delivery_check: bool = False,
    delivery_preset: str = "streaming",
) -> dict:
    """Full timeline render then trim to [start, end) for a segment file.

    Same cost as full export + cut — for cold-open/social slices, not a dirty-region optim.
    """
    return _require_editor().export_range(
        output_path,
        start_seconds,
        end_seconds,
        normalize_preset=normalize_preset,
        run_delivery_check=run_delivery_check,
        delivery_preset=delivery_preset,
    )


@mcp.tool()
def doctor(
    check_comfy: bool = True,
    comfy_host: str = "127.0.0.1",
    comfy_port: int = 8188,
) -> dict:
    """Environment health check before a film session.

    Verifies Python, ffmpeg/ffprobe, mcp, optional extras, optional ComfyUI.
    ok=false → fix errors (ffmpeg on PATH, pip install) before cutting.
    Also available as CLI: ``opmiere doctor``.
    """
    from .doctor import run_doctor
    return run_doctor(
        comfy_host=comfy_host,
        comfy_port=comfy_port,
        check_comfy=check_comfy,
    )


@mcp.tool()
def get_director_policy() -> dict:
    """Return the per-fragment quality-gate policy (ARCHITECTURE.md §5.10).

    Call with get_film_workflow at session start. Covers generate →
    quality_check → contact_sheet → place/upscale/redo. Does not mutate the
    project. Returns {version, policy} (markdown).
    """
    return _get_director_policy()


@mcp.tool()
def get_film_workflow() -> dict:
    """Return the full film-session process (materials → cut → export).

    Includes versioned markdown, DEFAULT_AESTHETIC when the user has no
    creative opinion, allowed asset roles, and an empty brief template.
    Pair with make_director_brief + plan_director_session. Does not edit
    the project.
    """
    return _get_film_workflow()


@mcp.tool()
def make_director_brief(
    intent: str | None = None,
    assets: list | None = None,
    constraints: dict | None = None,
    deliverable: dict | None = None,
) -> dict:
    """Build a structured director brief from user intake.

    intent: free-text creative goal; omit/empty = no_opinion and
      defaults_applied is filled from DEFAULT_AESTHETIC.
    assets: list of {path, role?} role one of a_roll|b_roll|vo|vo_ref|music|
      sfx|still|other.
    constraints: optional duration_seconds, language, no_generate, fps,
      width, height.
    deliverable: optional bundle_path (.opm), export_path (mp4).
    Does not validate filesystem (use validate_director_brief).
    """
    return _make_director_brief(
        intent=intent,
        assets=assets,
        constraints=constraints,
        deliverable=deliverable,
    )


@mcp.tool()
def validate_director_brief(brief: dict) -> dict:
    """Validate a director brief. Returns {ok, errors, warnings}.

    Missing asset paths are warnings (may be created later); structural
    problems are errors. Does not mutate the project.
    """
    return _validate_director_brief(brief)


@mcp.tool()
def plan_director_session(brief: dict) -> dict:
    """Return an ordered step plan for a brief (tool names + purposes).

    Does NOT execute edits or generation — the agent runs each step with the
    real tools. Prefer user assets; generate only listed gap kinds. Includes
    validation result under 'validation'. When no_opinion, 'defaults' echoes
    DEFAULT_AESTHETIC for grade/audio choices.
    """
    return _plan_director_session(brief)


@mcp.tool()
def apply_effect(clip_id: str, effect: dict) -> dict:
    """Apply a deterministic effect to a clip (rendered by ffmpeg, no AI generation).

    Effects stack in the order applied. Supported ``effect`` shapes:
      {"type": "color", "brightness": -1..1 (default 0), "contrast": 0..2 (default 1), "saturation": 0..3 (default 1)}
      {"type": "fade", "direction": "in"|"out", "duration_frames": N}
      {"type": "gain", "db": float}  (audio volume in decibels, e.g. 6.0 louder, -6.0 quieter)
      {"type": "text", "content": str, "position": "top"|"center"|"bottom" (default bottom), "size": int (default 48), "color": "white" (default), "border_width": int (default 2, a dark outline so text stays readable over bright/busy footage; 0 = no outline), "border_color": "black" (default), "font": optional path to a .ttf/.ttc (default is a CJK-capable font)}
      {"type": "blur", "amount": float (default 5.0, gaussian blur sigma - bigger is blurrier)}
      {"type": "vignette", "strength": float (default 1.0, bigger is a more visible dark-corner effect)}
      {"type": "chroma_key", "color": "green" (default), "similarity": 0..1 (default 0.15), "blend": 0..1 (default 0.05)}
        - keys the color transparent; put this clip on a video track above another
          (see add_track/add_clip) so the track underneath shows through.
      {"type": "luma_key", "threshold": 0..1 (default 0.1), "tolerance": 0..1 (default 0.1)}
        - same idea as chroma_key but keys by brightness, not a specific color
          (e.g. a white/black backdrop instead of green/blue).
      {"type": "curves", "preset": one of color_negative|cross_process|darker|increase_contrast|
        lighter|linear_contrast|medium_contrast|negative|strong_contrast|vintage}
        - a full-frame color-grade preset (ffmpeg's own curves vocabulary).
      {"type": "crop", "width": int, "height": int, "x": int (default centered), "y": int (default centered)}
      {"type": "rotate", "degrees": float, "fill": "black" (default) - color for corners the rotation
        exposes. Output frame size is unchanged (corners may clip), not auto-expanded.}
      {"type": "sharpen", "amount": 0..5 (default 1.0, bigger is a stronger sharpen)}
      {"type": "film_grain", "amount": 0..100 (default 20.0, bigger is heavier/coarser grain)}
      {"type": "glow", "amount": 0..50 (default 12.0, blur radius of the light halo - bigger is softer/wider),
        "intensity": 0..1 (default 0.7, how hard the halo is screen-blended onto the base)}
        - soft bloom around bright areas: blurs a copy of the frame and screen-blends it back
          (multi-stage filtergraph, not a single ffmpeg filter).
      {"type": "lut3d", "path": str (required, filesystem path to a .cube or .3dl 3D LUT file),
        "interp": "nearest"|"trilinear"|"tetrahedral"|"pyramid"|"prism" (default tetrahedral)}
        - full-frame color grade from an external LUT; path must exist at apply time.
      {"type": "ken_burns", "zoom_start": 1..10 (default 1.0), "zoom_end": 1..10 (default 1.2),
        "x_start"/"y_start"/"x_end"/"y_end": 0..1 (default 0.5 = center focus)}
        - animated zoom+pan over the clip (zoompan d=1). zoom 1 = full frame; higher zooms in.
          Focus points are fractions of the frame. Chain must not scale after this effect
          (handled internally).
      {"type": "white_balance", "temperature": 1000..40000 Kelvin (default 6500 = daylight neutral;
        lower = warmer/amber, higher = cooler/blue), "mix": 0..1 (default 1.0, blend with source)}
        - full-frame color temperature shift (ffmpeg colortemperature). Use for cold→warm emotion arcs
          without re-generating.
      {"type": "shape_mask", "shape": "circle"|"rect" (default circle),
        "cx"/"cy": 0..1 center (default 0.5), "size": 0..1 (circle radius as fraction of half min-side,
        default 0.5), "width"/"height": 0..1 (rect only, default 0.5), "feather": 0..1 soft edge
        (default 0.05), "invert": bool (default false)}
        - geometric alpha mask; put the clip on an overlay video track so the layer below shows outside
          the shape (same alpha-survival rules as chroma_key).
      {"type": "subtitles", "path": str (required, .srt/.ass), "force_style": optional ASS style string}
        - burn timed captions (from transcribe/write_srt or caption_clip) into the clip.
      {"type": "compression", "threshold_db": float (default -18.0, level where compression kicks in),
        "ratio": 1..20 (default 4.0), "attack_ms": float (default 20.0), "release_ms": float
        (default 250.0), "makeup_db": float (default 0.0, gain added back after compressing)}
        - audio dynamic range compression (evens out loud/quiet parts), not video.
      {"type": "noise_reduction", "amount": 0.01..97 (default 12.0, dB of noise reduction - bigger
        is more aggressive, can start eating the wanted signal past a point)}
        - spectral denoise (ffmpeg's afftdn) for hiss/hum in a recording, not video.
      {"type": "audio_eq", "frequency_hz": 20..20000 (required, center of the band), "gain_db": -24..24
        (default 0, positive boosts that frequency, negative cuts it), "q": 0..10 (default 1.0, bigger
        is a narrower/more surgical band, smaller is broader)}
        - one parametric EQ band; apply_effect it again at a different frequency_hz to stack more bands
          (effects apply in the order added, same as everything else here) for a multi-band EQ.
    A fade's duration_frames must not exceed the clip's own duration_frames
    (visible in get_project_state).
    """
    return _require_editor().apply_effect(clip_id, effect).to_dict()


@mcp.tool()
def add_transition(clip_id: str, transition_type: str, duration_frames: int) -> dict:
    """Transition clip_id in from whatever clip precedes it on its track.

    transition_type: "cross_dissolve" (classic dissolve), "dip_to_black" or
    "dip_to_white" (fade through a solid color, not directly into the next
    shot), or "wipe_left"/"wipe_right"/"wipe_up"/"wipe_down" (the new shot
    slides in over the old one). Video-only styling - the audio underneath
    always crossfades the same way regardless of which visual type you pick.
    The boundary must currently be a clean hard cut (this clip's start == the
    previous clip's end) - check get_project_state first. Prefer place_after(
    ..., transition_type=..., transition_frames=...) which does hard-cut then
    transition for you. This shortens the combined timeline by duration_frames.
    """
    return _require_editor().add_transition(clip_id, transition_type, duration_frames).to_dict()


@mcp.tool()
def place_after(
    after_clip_id: str,
    media_id: str,
    src_in: int = 0,
    src_out: int | None = None,
    transition_type: str | None = None,
    transition_frames: int | None = None,
) -> dict:
    """Place media as the next clip after after_clip_id (hard cut at prev.end).

    Optional transition_type + transition_frames then dissolve it in — the
    correct order agents kept getting wrong (place pre-overlapped then
    add_transition was rejected). src_out defaults to full media duration.
    """
    return _require_editor().place_after(
        after_clip_id, media_id, src_in, src_out, transition_type, transition_frames
    ).to_dict()


@mcp.tool()
def remove_transition(clip_id: str) -> dict:
    """Remove a previously-added transition_in from a clip, restoring its start."""
    return _require_editor().remove_transition(clip_id).to_dict()


@mcp.tool()
def set_speed(clip_id: str, speed: float) -> dict:
    """Change a clip's playback rate (1.0 = normal, 2.0 = double speed, 0.5 =
    half speed). Doesn't change which source frames are used, only how much
    timeline space they occupy - the clip's duration on the timeline shrinks
    (speed > 1) or grows (speed < 1) accordingly; check get_project_state
    afterward if you need the new end position. Audio speed is limited to
    0.5-2.0 (a real ffmpeg constraint); video speed has no such limit.
    """
    return _require_editor().set_speed(clip_id, speed).to_dict()


@mcp.tool()
def set_position(clip_id: str, x: float, y: float, scale: float) -> dict:
    """Place a clip as picture-in-picture instead of full-frame. Only has a
    visible effect when the clip is on an overlay video track (any video
    track after the first one on the project - see add_track/add_clip and
    the "chroma_key" note under apply_effect); the base track always renders
    full-frame regardless.

    scale: 0 < scale <= 1, the box's size as a fraction of the canvas
    (aspect preserved, matching how full-frame clips already fit).
    x, y: each 0..1, the box's top-left corner as a fraction of the room it
    has to move in (canvas size minus box size) - 0 is flush against that
    edge, 1 is flush against the opposite edge, so any value keeps the whole
    box on-canvas. E.g. x=1, y=1, scale=0.25 puts a quarter-size box in the
    bottom-right corner.
    """
    return _require_editor().set_position(clip_id, x, y, scale).to_dict()


@mcp.tool()
def clear_position(clip_id: str) -> dict:
    """Restore a clip (previously set via set_position) to full-frame."""
    return _require_editor().clear_position(clip_id).to_dict()


@mcp.tool()
def set_ducking(
    track_id: str,
    against_track_id: str,
    threshold_db: float = -30.0,
    ratio: float = 8.0,
    attack_ms: float = 20.0,
    release_ms: float = 300.0,
    makeup_db: float = 0.0,
) -> dict:
    """Automatically dip track_id's volume whenever against_track_id has
    signal - the classic "music ducks under the voiceover" move, without
    hand-placing gain changes around every spoken line. Both must be audio
    tracks; the against-track's own sound is unchanged (it only *triggers*
    the dip). One duck relationship per track (calling again replaces it).

    threshold_db: level the against-track must exceed to trigger (default
    -30, low enough that normal speech triggers reliably). ratio: how hard
    the dip is (default 8 - clearly audible; 2-3 is gentle). attack_ms /
    release_ms: how fast the dip engages / lets go (defaults 20/300 - the
    slow release avoids pumping between words). makeup_db: gain added back
    after compression (default 0). Verify the result with analyze_audio on
    the export."""
    return (
        _require_editor()
        .set_ducking(
            track_id, against_track_id,
            threshold_db=threshold_db, ratio=ratio,
            attack_ms=attack_ms, release_ms=release_ms, makeup_db=makeup_db,
        )
        .to_dict()
    )


@mcp.tool()
def clear_ducking(track_id: str) -> dict:
    """Remove a duck relationship previously set on track_id via set_ducking."""
    return _require_editor().clear_ducking(track_id).to_dict()


@mcp.tool()
def analyze_audio(
    path: str,
    image_path: str | None = None,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.5,
) -> dict:
    """The audio counterpart of make_contact_sheet - the agent's "ears".
    Meters any audio-bearing file: mean/max volume (dB), integrated loudness
    (LUFS - streaming targets sit around -14, music beds under speech much
    lower), loudness range (LU), true peak (dBFS - near 0 warns of clipping),
    and silence regions longer than min_silence_seconds below
    silence_threshold_db. Pass image_path (a .png) to also get a waveform +
    spectrogram picture - read it as an image to see dynamics over time and
    frequency content (hiss, harshness, missing bass) that single numbers
    hide. Use on generated audio before placing it, and on exports to verify
    the mix (e.g. that ducking actually made room for the voiceover).
    Deterministic ffmpeg analysis - free, local, no model call.
    For the *current project mix* (ducking/multi-track), use analyze_timeline
    instead — this tool only sees a single file path."""
    return _require_editor().analyze_audio(
        path,
        image_path,
        silence_threshold_db=silence_threshold_db,
        min_silence_seconds=min_silence_seconds,
    )


@mcp.tool()
def analyze_timeline(
    image_path: str | None = None,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.5,
) -> dict:
    """Meter the current project mix (all tracks, ducking, levels as authored).

    Exports to a temp file, runs the same meters as analyze_audio, deletes the
    temp. Use this to verify ducking/music beds before choosing a final export
    path — analyze_audio alone cannot see the live timeline.
    """
    return _require_editor().analyze_timeline(
        image_path,
        silence_threshold_db=silence_threshold_db,
        min_silence_seconds=min_silence_seconds,
    )


@mcp.tool()
def recommend_generation_profile(kind: str, offload: bool = False) -> dict:
    """Which model to pass as generate(kind, params={"model": ...}) on this
    machine, based on real detected VRAM (ComfyUI's /system_stats) rather
    than a guess - ARCHITECTURE.md 5.7's generation-profiles system.

    kind: "image", "video", or "speech".
    offload=False (default): the best model that actually fits detected
      VRAM outright - fast and safe, no swapping.
    offload=True: the best model in the offload track regardless of fit -
      deliberately trades speed for quality via ComfyUI's own automatic
      model paging (RAM/disk as VRAM overflow, confirmed real - see
      generation/profiles.py). Only "video" has an offload-tier profile
      today (wan2.2-moe); image/speech will raise until one exists.

    Call this before generate() when unsure which model param to pass,
    especially on hardware other than the reference RTX 3070 (8GB) these
    profiles were measured on - the recommendation adapts, the underlying
    measurements don't (yet re-benchmarked per machine).
    """
    profile = _get_generation_provider().recommend_profile(kind, offload=offload)
    return profile.to_dict()


@mcp.tool()
def generate(kind: str, prompt: str, params: dict | None = None) -> str:
    """Submit an async local-GPU generation job and return a job id immediately.

    Runs on the local ComfyUI server. Poll job_status(job_id) until status is
    "done" (or "error"), then place_generated() to add it to the timeline -
    do not assume it finished just because submit succeeded.

    kind="image": prompt is the image description. Params: model - one of
      "sd1.5" (default, fast, Apache-friendly OpenRAIL license, ~7s),
      "flux-schnell" (much higher quality, Apache-2.0, ~34s), "flux-dev"
      (highest quality, but FLUX.1-dev Non-Commercial License - free for
      personal/research only; use get_license_report() before shipping/
      selling anything placed from a flux-dev job). Also: width/height
      (default 512, flux models default to 1024), steps (default 20 for
      sd1.5, 4 for flux-schnell, 20 for flux-dev), cfg (default 7.0 for
      sd1.5, 1.0 for flux models), seed, negative_prompt.

    kind="video": prompt is the video description (long, descriptive prompts
      work much better than short ones). Params: model - one of "ltx-video"
      (default, fast, ~22s, Lightricks Open Weights License - free only
      below $10M company ARR, see get_license_report()), "wan2.1" (visibly
      sharper/more coherent than ltx-video, Apache-2.0, ~6x slower (~140s)
      and closer to the 8GB ceiling (~7.7GB peak vs ~6.4GB) - still
      non-offload, just less headroom), or "wan2.2-moe" (the offload-tier
      option: two 8.75GB GGUF experts, 17.5GB combined, neither fits this
      8GB card alongside the other - ComfyUI's own model paging swaps them
      in/out automatically (confirmed via real VRAM sampling: it oscillates
      ~4-8GB, never needs both at once), no special config required. Best
      quality of the three in testing, ~283s for a small 480x480/17-frame
      run - noticeably slower, the accepted tradeoff for going past what
      fits natively. Apache-2.0). Also: width/height (ltx-video 512/320,
      wan2.1 832/480, wan2.2-moe 480/480), num_frames (ltx-video 65, wan2.1
      33, wan2.2-moe 17), frame_rate (ltx-video 25, wan2.1/wan2.2-moe 16 -
      should match the target project's timebase.fps, see get_project_state,
      or place_generated will reject it as a mismatch later), steps
      (ltx-video/wan2.1 30, wan2.2-moe 20 split across both experts via
      split_step, default half), cfg (ltx-video 3.0, wan2.1 6.0, wan2.2-moe
      3.5), seed, negative_prompt.

    kind="speech": prompt is the text to speak. Two modes:
      - preset voice (no reference needed): params speaker (default
        "Vivian"; others: Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden,
        Ono_Anna, Sohee), language (default "Auto").
      - voice cloning: params reference_audio (path to a short 1-10s clean
        clip of the voice to clone) AND reference_text (its exact
        transcript - both required together). Only clone a voice with the
        speaker's knowledge/consent.

    kind="music": prompt is the tags description - comma-separated genre/
      mood/instrument descriptors (ACE-Step's own vocabulary), e.g. "warm
      acoustic guitar, gentle piano, hopeful, cinematic underscore" - not a
      natural-language sentence. Params: seconds (default 30), lyrics
      (default "[instrumental]" for background-score use; pass real lyrics
      with [verse]/[chorus] markers for a sung track), lyrics_strength
      (default 1.0), steps (default 50), cfg (default 5.0), seed.
      Apache-2.0, ~7.5GB VRAM, ~24s for 30s of audio on an 8GB GPU.

    kind="sfx": prompt is a natural-language sound description (e.g.
      "glass bottle shattering on concrete, short sharp impact"), NOT music
      tags. Local Stable Audio Open 1.0 via ComfyUI. Params: seconds
      (default 8, range [1, 47]), steps (default 50), cfg (default 4.98),
      negative_prompt, seed. License is Stability AI Community License
      (free under $1M ARR — use get_license_report() before shipping).

    kind="upscale": the "finish" half of the draft->finish workflow
      (ARCHITECTURE.md 5.7 D) as an alternative to re-running a full
      generation at a higher quality tier - a deterministic 4x super-
      resolution pass (no seed/steps/cfg, so results are stable and it's
      cheap relative to a re-generate). prompt is ignored (pass "");
      required param source_path - the local image *or video* file to
      upscale (typically a draft job's own result_path after quality_check).
      Images go through ComfyUI's ImageUpscaleWithModel once; multi-frame
      video is frame-extract → same upscale per frame → reassemble (audio
      preserved from the source). Optional max_frames (default 300) caps
      how long a video upscale is willing to run without an explicit opt-in.
      Model: RealESRGAN_x4plus (BSD-3-Clause, commercial-safe).
    """
    return _require_editor().generate(kind, prompt, params or {})


@mcp.tool()
def job_status(job_id: str) -> dict:
    """Poll a generation job. status is one of queued/running/done/error.

    result_path is only set once status == "done"; error is only set once
    status == "error" (with the real underlying message, not a guess).
    license is only set once status == "done" and the provider knows which
    checkpoint made it (see get_license_report for a whole-project audit).
    """
    job = _require_editor().job_status(job_id)
    return {
        "id": job.id,
        "status": job.status.value,
        "kind": job.kind,
        "prompt": job.prompt,
        "result_path": str(job.result_path) if job.result_path else None,
        "error": job.error,
        "license": job.license.to_dict() if job.license else None,
    }


@mcp.tool()
def place_generated(job_id: str, track_id: str, start: int, duration_frames: int | None = None) -> dict:
    """Import a finished job's result into the project and place it as a clip.

    The job must already be "done" (check job_status first - this raises
    rather than silently waiting if it isn't). The resulting Media's origin
    field records the provider/job/prompt that made it, visible later in
    get_project_state.

    duration_frames is optional for video/speech/sfx/music - omit it to use
    the generated clip's full real duration (you rarely know a generated
    clip's exact length ahead of time, especially for speech). Required for
    kind="image", which has no intrinsic duration.
    """
    return _require_editor().place_generated(job_id, track_id, start, duration_frames).to_dict()


@mcp.tool()
def get_license_report() -> dict:
    """Audit every generated media asset placed in this project for licenses
    that restrict commercial use (e.g. flux-dev's non-commercial license).

    Metadata only - sourced from each Media's origin, recorded automatically
    by place_generated(); never touches the generated content itself.
    safe_for_commercial_use is False if anything in flagged needs a paid/
    separate license before the project can be sold or published commercially.
    """
    return _require_editor().get_license_report()


@mcp.tool()
def quality_check(path: str) -> dict:
    """Free, deterministic checks a media file passes/fails before spending
    an agent's own attention on it: is_black, is_static (frozen picture -
    the "generated video that's just one still frame" failure mode),
    is_blurry, is_silent. No model call, no pixels sent anywhere - plain
    ffmpeg analysis (blackdetect/freezedetect/blurdetect/silencedetect).

    Call this on a generation job's result_path (from job_status) before
    place_generated commits it to the timeline - catching an obviously
    broken generation for free beats discovering it after export. issues
    lists what failed in plain language; passed is the overall verdict.
    is_blurry/is_silent are None when that check doesn't apply (no video or
    no audio stream).
    """
    return _require_editor().quality_check(path)


@mcp.tool()
def transcribe(
    path: str,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    word_timestamps: bool = True,
) -> dict:
    """Speech-to-text on a local audio/video file (faster-whisper).

    Returns language, segments[{start,end,text,words?}], model_size. Does not
    write SRT — use write_srt or caption_clip. Requires pip install faster-whisper.
    """
    return _require_editor().transcribe(
        path,
        model_size=model_size,
        language=language,
        device=device,
        compute_type=compute_type,
        word_timestamps=word_timestamps,
    )


@mcp.tool()
def write_srt(path: str, segments: list) -> str:
    """Write transcript segments to an .srt file. Returns the path written."""
    return _require_editor().write_srt(path, segments)


@mcp.tool()
def suggest_silence_cuts(
    path: str,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.4,
    pad_seconds: float = 0.08,
    min_keep_seconds: float = 0.2,
) -> dict:
    """Suggest keep_ranges between silences (cut dead air). Pure ffmpeg.

    Does not edit the timeline — agent applies trim/split using the ranges.
    """
    return _require_editor().suggest_silence_cuts(
        path,
        silence_threshold_db=silence_threshold_db,
        min_silence_seconds=min_silence_seconds,
        pad_seconds=pad_seconds,
        min_keep_seconds=min_keep_seconds,
    )


@mcp.tool()
def transcribe_media(
    media_id: str,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    word_timestamps: bool = True,
    cache: bool = True,
) -> dict:
    """Transcribe a registered media asset; caches under analysis/transcripts/."""
    return _require_editor().transcribe_media(
        media_id,
        model_size=model_size,
        language=language,
        device=device,
        compute_type=compute_type,
        word_timestamps=word_timestamps,
        cache=cache,
    )


@mcp.tool()
def search_transcripts(
    query: str,
    media_id: str | None = None,
    max_hits: int = 20,
) -> dict:
    """Keyword search cached transcripts (“找到我说但是…” → timestamps).

    Run transcribe_media first. Omit media_id to search all cached assets.
    """
    return _require_editor().search_transcripts(
        query, media_id=media_id, max_hits=max_hits,
    )


@mcp.tool()
def suggest_filler_cuts(
    clip_id: str | None = None,
    media_id: str | None = None,
    path: str | None = None,
    extra_words: list[str] | None = None,
    pad_seconds: float = 0.02,
    model_size: str = "base",
    language: str | None = None,
) -> dict:
    """Plan filler-word cuts (um/uh/那个/就是…) from word-level ASR.

    Returns cut_ranges + keep_ranges. Does not edit — use apply_filler_cuts.
    """
    return _require_editor().suggest_filler_cuts(
        path=path,
        clip_id=clip_id,
        media_id=media_id,
        extra_words=extra_words,
        pad_seconds=pad_seconds,
        model_size=model_size,
        language=language,
    )


@mcp.tool()
def apply_keep_ranges(
    clip_id: str,
    keep_ranges: list,
    time_unit: str = "seconds",
) -> dict:
    """Replace one clip with pieces for keep_ranges (source seconds/frames)."""
    return _require_editor().apply_keep_ranges(
        clip_id, keep_ranges, time_unit=time_unit,
    )


@mcp.tool()
def apply_filler_cuts(
    clip_id: str,
    dry_run: bool = True,
    extra_words: list[str] | None = None,
    pad_seconds: float = 0.02,
    model_size: str = "base",
    language: str | None = None,
) -> dict:
    """Filler 粗剪: plan from ASR; dry_run=false applies keep ranges (ripple).

    Default dry_run=true so agents review before cutting.
    """
    return _require_editor().apply_filler_cuts(
        clip_id,
        dry_run=dry_run,
        extra_words=extra_words,
        pad_seconds=pad_seconds,
        model_size=model_size,
        language=language,
    )


@mcp.tool()
def caption_clip(
    clip_id: str,
    srt_path: str | None = None,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict:
    """Transcribe a clip's media, write SRT, burn subtitles via apply_effect.

    Returns {clip, srt_path, transcript}. Needs faster-whisper installed.
    """
    return _require_editor().caption_clip(
        clip_id,
        srt_path=srt_path,
        model_size=model_size,
        language=language,
        device=device,
        compute_type=compute_type,
    )


@mcp.tool()
def detect_scenes(
    path: str,
    threshold: float = 27.0,
    min_scene_len: int = 15,
    backend: str = "auto",
) -> dict:
    """Detect shot/scene boundaries in a video.

    backend: auto (PySceneDetect if installed else ffmpeg), scenedetect, or
    ffmpeg. Returns scenes[{start,end,duration,start_frame,end_frame}].
    Agent uses these to split long footage onto the timeline.
    """
    return _require_editor().detect_scenes(
        path, threshold=threshold, min_scene_len=min_scene_len, backend=backend,
    )


@mcp.tool()
def suggest_project_fps(paths: list[str] | None = None, preference: str = "auto") -> dict:
    """Recommend timeline fps from source videos.

    preference: auto | 24 | 25 | 30 | 50 | 60. Highest honest option is 60 when
    sources support it. Prefer matching user A-roll; do not drag the whole
    project to 16fps just because one generated draft is 16. If requested >
    source max, response includes warnings — agent must tell the user.
    Works without an open project (pure analysis).
    """
    from .render.asset_analysis import suggest_project_fps as _sug_fps
    return _sug_fps(paths, preference=preference)


@mcp.tool()
def suggest_project_resolution(paths: list[str] | None = None, preference: str = "auto") -> dict:
    """Recommend timeline resolution (720p / 1080p / 1440p / 4k).

    preference: auto | 720p | 1080p | 1440p | 4k. If target exceeds largest
    source, feasible_native=false and errors are set — agent must NOT claim
    native 4k output from 1080p (or lower) footage; lower the canvas or get
    higher-res material. Works without an open project.
    """
    from .render.asset_analysis import suggest_project_resolution as _sug_res
    return _sug_res(paths, preference=preference)


@mcp.tool()
def check_delivery_limits(
    paths: list[str] | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """Gate before create_project/export: can we honestly claim this delivery?

    ok=false means requested fps and/or resolution exceeds sources. Agent must
    warn the user and lower targets or obtain better material — upscale is not
    free quality. Works without an open project.
    """
    from .render.asset_analysis import check_delivery_limits as _check
    return _check(paths=paths, fps=fps, width=width, height=height)


@mcp.tool()
def plan_edit(
    paths: list[str] | None = None,
    cards: list[dict] | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
    cut_silence: bool = True,
    prefer_scenes: bool = True,
    max_clip_seconds: float | None = None,
    transition_default: str = "auto",
    transition_frames: int = 12,
    analyze_if_needed: bool = True,
    b_roll_mode: str = "overlay",
    target_duration_seconds: float | None = None,
    j_cut_seconds: float = 0.4,
    l_cut_seconds: float = 0.25,
    b_roll_max_seconds: float = 2.5,
    use_music_beats: bool = True,
    black_pad_j_cut: bool = True,
) -> dict:
    """Build an EDL-like edit plan from asset paths or analyze_asset cards.

    b_roll_mode=overlay: cutaways on video_overlay (speech → music beats →
    even). black_pad_j_cut: true opening J-cut pad. Review then apply_edit_plan.
    """
    kwargs = dict(
        cards=cards,
        paths=paths,
        fps=fps,
        width=width,
        height=height,
        cut_silence=cut_silence,
        prefer_scenes=prefer_scenes,
        max_clip_seconds=max_clip_seconds,
        transition_default=transition_default,
        transition_frames=transition_frames,
        analyze_if_needed=analyze_if_needed,
        b_roll_mode=b_roll_mode,
        target_duration_seconds=target_duration_seconds,
        j_cut_seconds=j_cut_seconds,
        l_cut_seconds=l_cut_seconds,
        b_roll_max_seconds=b_roll_max_seconds,
        use_music_beats=use_music_beats,
        black_pad_j_cut=black_pad_j_cut,
    )
    if _editor is not None:
        return _editor.plan_edit(**kwargs)
    from .render.asset_analysis import plan_edit as _plan
    kwargs["fps"] = float(fps if fps is not None else 30)
    kwargs["width"] = width if width is not None else 1920
    kwargs["height"] = height if height is not None else 1080
    return _plan(**kwargs)


@mcp.tool()
def apply_edit_plan(
    plan: dict,
    track_ids: dict[str, str] | None = None,
    skip_missing: bool = False,
) -> dict:
    """Apply a plan_edit result: import media, place clips, add transitions.

    Supports timeline_start_frames for overlay/audio (gaps OK). track_ids maps
    track_hint → existing track id. Returns placed clip ids + errors.
    """
    return _require_editor().apply_edit_plan(
        plan, track_ids=track_ids, skip_missing=skip_missing,
    )


@mcp.tool()
def detect_beats(
    path: str,
    max_seconds: float | None = 180.0,
    sensitivity: float = 1.15,
) -> dict:
    """Detect beat/onset times in a music or video file (energy peak-pick).

    Returns beat_times[], bpm_estimate. Use for cutaway landing or to feed
    plan_edit (use_music_beats=true is default when music is in assets).
    """
    from .render.beats import detect_beats as _db
    if _editor is not None:
        return _editor.detect_beats(path, max_seconds=max_seconds, sensitivity=sensitivity)
    return _db(path, max_seconds=max_seconds, sensitivity=sensitivity)


@mcp.tool()
def suggest_mix(
    vo_path: str | None = None,
    music_path: str | None = None,
    sfx_path: str | None = None,
    vo_track_id: str | None = None,
    music_track_id: str | None = None,
    target_vo_lufs: float = -16.0,
    target_music_lufs: float = -22.0,
) -> dict:
    """Suggest VO/music gains + set_ducking from real LUFS/volume meters.

    Pass stem paths (best). Then apply_mix_plan or apply_effect gain + set_ducking.
    """
    from .render.mix_suggest import suggest_mix as _sm
    if _editor is not None:
        return _editor.suggest_mix(
            vo_path=vo_path,
            music_path=music_path,
            sfx_path=sfx_path,
            vo_track_id=vo_track_id,
            music_track_id=music_track_id,
            target_vo_lufs=target_vo_lufs,
            target_music_lufs=target_music_lufs,
        )
    return _sm(
        vo_path=vo_path,
        music_path=music_path,
        sfx_path=sfx_path,
        vo_track_id=vo_track_id,
        music_track_id=music_track_id,
        target_vo_lufs=target_vo_lufs,
        target_music_lufs=target_music_lufs,
    )


@mcp.tool()
def suggest_dialogue_chain(path: str, has_music_bleed: bool = False) -> dict:
    """Recommended denoise → compress → gain chain for a dialogue/VO file."""
    from .render.mix_suggest import suggest_dialogue_chain as _sdc
    if _editor is not None:
        return _editor.suggest_dialogue_chain(path, has_music_bleed=has_music_bleed)
    return _sdc(path, has_music_bleed=has_music_bleed)


@mcp.tool()
def apply_mix_plan(
    plan: dict,
    role_clip_ids: dict[str, list[str]] | None = None,
    music_track_id: str | None = None,
    vo_track_id: str | None = None,
) -> dict:
    """Apply suggest_mix actions (gain on role clips + set_ducking)."""
    return _require_editor().apply_mix_plan(
        plan,
        role_clip_ids=role_clip_ids,
        music_track_id=music_track_id,
        vo_track_id=vo_track_id,
    )


@mcp.tool()
def list_look_presets() -> dict:
    """List project look names (cool_setup, warm_resolve, cinematic, …)."""
    return _require_editor().list_look_presets()


@mcp.tool()
def list_style_presets() -> dict:
    """Film aesthetic styles (ang_lee, horror, wes_anderson, cyberpunk, …).

    Parameter library for agent blend — not generative invent-a-look.
    """
    return _require_editor().list_style_presets()


@mcp.tool()
def apply_style_preset(
    styles: str,
    clip_ids: list[str] | None = None,
    video_only: bool = True,
) -> dict:
    """Apply blended film style(s) as deterministic effects.

    styles: comma or + separated names, e.g. \"ang_lee,horror\" or \"ang_lee+horror\".
    Returns resolved pacing/transition hints + effects applied.
    """
    return _require_editor().apply_style_preset(
        styles, clip_ids=clip_ids, video_only=video_only,
    )


@mcp.tool()
def apply_project_look(
    look: str = "cinematic",
    clip_ids: list[str] | None = None,
    video_only: bool = True,
) -> dict:
    """Apply one grade language to all (or listed) video clips.

    look: neutral|cool_setup|warm_resolve|cinematic|vintage|documentary.
    Prefer this over regenerating for continuity. Then sequence contact sheet.
    For film aesthetics (李安/恐怖), prefer apply_style_preset.
    """
    return _require_editor().apply_project_look(
        look, clip_ids=clip_ids, video_only=video_only,
    )


@mcp.tool()
def color_match_to_clip(
    reference_clip_id: str,
    clip_ids: list[str] | None = None,
    strength: float = 0.65,
) -> dict:
    """Match other clips' grade toward a reference clip (signalstats + eq/WB).

    strength 0..1 (default 0.65). Does not invent detail — deterministic only.
    """
    return _require_editor().color_match_to_clip(
        reference_clip_id, clip_ids, strength=strength,
    )


@mcp.tool()
def analyze_asset(
    path: str,
    do_scenes: bool = True,
    do_silence: bool = True,
    do_motion: bool = True,
    do_transcribe: bool = False,
    scene_backend: str = "auto",
    language: str | None = None,
    model_size: str = "base",
    cache: bool = True,
) -> dict:
    """Professional asset card for one media file.

    Returns probe, scenes, silence keep_ranges, motion label, transition
    affinity (preferred in/out), role_guess, suggested_uses. Optional ASR
    when do_transcribe=true (needs faster-whisper). Caches under .opm/analysis/.
    Use before plan_edit / place to allocate shots intelligently.
    """
    return _require_editor().analyze_asset(
        path,
        do_scenes=do_scenes,
        do_silence=do_silence,
        do_motion=do_motion,
        do_transcribe=do_transcribe,
        scene_backend=scene_backend,
        language=language,
        model_size=model_size,
        cache=cache,
    )


@mcp.tool()
def separate_stems(
    path: str,
    output_dir: str,
    model: str = "htdemucs",
    two_stems: str | None = "vocals",
    device: str = "cpu",
) -> dict:
    """Separate vocals vs accompaniment (Demucs). Needs pip install demucs.

    Default two_stems=vocals → vocals.wav + no_vocals.wav under output_dir.
    Place stems with place_from_file; duck/mute original dialogue as needed.
    """
    return _require_editor().separate_stems(
        path, output_dir, model=model, two_stems=two_stems, device=device,
    )


@mcp.tool()
def make_contact_sheet(path: str, output_path: str, cols: int = 3, rows: int = 3) -> str:
    """Tile cols*rows evenly-spaced thumbnails from a video into one small
    grid image - the cheap way to actually *look* at a shot's motion/
    composition (ARCHITECTURE.md 5.10's agent-director loop) without the
    token cost of many full-res frames. Returns the written image path -
    read it (as an image) to judge the shot. Use after quality_check passes,
    for the judgment calls quality_check can't make (composition, subject
    fidelity, does the motion look right).
    """
    return _require_editor().make_contact_sheet(path, output_path, cols=cols, rows=rows)


@mcp.tool()
def undo() -> bool:
    """Undo the last edit. Returns False if there is nothing to undo."""
    return _require_editor().undo()


@mcp.tool()
def redo() -> bool:
    """Redo the last undone edit. Returns False if there is nothing to redo."""
    return _require_editor().redo()


@mcp.tool()
def save_project() -> str:
    """Persist the current in-memory project to its bundle's project.json."""
    editor = _require_editor()
    editor.save()
    return str(editor.bundle.project_path)


@mcp.tool()
def make_sequence_contact_sheet(
    output_path: str,
    max_tiles: int = 12,
    tile_width: int = 160,
    tile_height: int = 90,
    cols: int | None = None,
) -> dict:
    """Whole-cut eyes: mid-frame of each base-track clip in one grid image.

    Read the returned image to judge pacing/continuity. Use after structure,
    before or after export. Not a substitute for delivery_check on the file.
    """
    return _require_editor().make_sequence_contact_sheet(
        output_path,
        max_tiles=max_tiles,
        tile_width=tile_width,
        tile_height=tile_height,
        cols=cols,
    )


@mcp.tool()
def review_cut(
    min_clip_seconds: float = 0.4,
    max_brightness_jump: float = 45.0,
    check_brightness_jumps: bool = True,
    expect_music_duck: bool = True,
) -> dict:
    """Structural craft review of the live timeline.

    Flags gaps/overlaps, flash-cut short clips, hard-cut brightness jumps,
    multi-audio without ducking. Fix severity=error before export; treat
    warnings as craft notes. Pair with make_sequence_contact_sheet.
    """
    return _require_editor().review_cut(
        min_clip_seconds=min_clip_seconds,
        max_brightness_jump=max_brightness_jump,
        check_brightness_jumps=check_brightness_jumps,
        expect_music_duck=expect_music_duck,
    )


@mcp.tool()
def normalize_loudness(
    path: str,
    output_path: str,
    preset: str = "streaming",
    target_lufs: float | None = None,
    true_peak: float | None = None,
    lra: float | None = None,
    two_pass: bool = True,
) -> dict:
    """Loudness-normalize a file (export or stem) to a platform target.

    preset: streaming|youtube|bilibili|douyin|podcast|broadcast
    (streaming ≈ -14 LUFS / -1.5 dBTP). Returns before/after meters.
    Then run delivery_check on output_path.
    """
    return _require_editor().normalize_loudness(
        path,
        output_path,
        preset=preset,
        target_lufs=target_lufs,
        true_peak=true_peak,
        lra=lra,
        two_pass=two_pass,
    )


@mcp.tool()
def delivery_check(
    path: str,
    preset: str = "streaming",
    target_lufs: float | None = None,
    true_peak_limit: float | None = None,
    lufs_tolerance: float = 1.5,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
    expected_duration_seconds: float | None = None,
    run_quality_check: bool = True,
    match_project: bool = True,
) -> dict:
    """Honest gate on a finished export — do not call it final if ok=false.

    Checks LUFS/true-peak vs preset, resolution/fps vs project (when
    match_project), optional quality_check (black/frozen/silent). Agent must
    warn the user or fix (normalize_loudness / re-export) when errors present.
    """
    return _require_editor().delivery_check(
        path,
        preset=preset,
        target_lufs=target_lufs,
        true_peak_limit=true_peak_limit,
        lufs_tolerance=lufs_tolerance,
        expected_width=expected_width,
        expected_height=expected_height,
        expected_fps=expected_fps,
        expected_duration_seconds=expected_duration_seconds,
        run_quality_check=run_quality_check,
        match_project=match_project,
    )


@mcp.tool()
def export_preview(
    output_path: str | None = None,
    height: int = 360,
    fps: float = 12.0,
    force: bool = False,
) -> dict:
    """Build a low-res timeline proxy for scrubbing (not delivery).

    force=false reuses a fresh proxy (cache hit). Auto-invalidated on
    mutate/undo/redo. Prefer ensure_preview_proxy for agent loops.
    """
    return _require_editor().export_preview(
        output_path, height=height, fps=fps, force=force,
    )


@mcp.tool()
def ensure_preview_proxy(
    output_path: str | None = None,
    height: int = 360,
    fps: float = 12.0,
) -> dict:
    """Build preview proxy only if missing/stale; else return cache hit."""
    return _require_editor().ensure_preview_proxy(
        output_path, height=height, fps=fps,
    )


@mcp.tool()
def preview_proxy_status() -> dict:
    """Whether the last export_preview is still fresh for the current timeline."""
    return _require_editor().preview_proxy_status()


@mcp.tool()
def frame_at(
    time_seconds: float,
    output_path: str,
    width: int = 640,
    prefer_proxy: bool = True,
) -> dict:
    """Grab one frame at timeline time for cheap eyes.

    Uses last *fresh* export_preview proxy when present (includes overlays);
    else base-track source seek (approximate). Stale proxy falls back safely.
    """
    return _require_editor().frame_at(
        time_seconds, output_path, width=width, prefer_proxy=prefer_proxy,
    )


@mcp.tool()
def review_keyframes(
    output_dir: str,
    count: int = 5,
    width: int = 640,
    ensure_proxy: bool = True,
) -> dict:
    """Evenly spaced frames across the cut (0%…100%) for pacing/continuity.

    ensure_proxy=true builds/reuses scrub proxy first. Read the image paths.
    """
    return _require_editor().review_keyframes(
        output_dir, count=count, width=width, ensure_proxy=ensure_proxy,
    )


@mcp.tool()
def preview_range(
    output_path: str,
    start_seconds: float,
    end_seconds: float,
    ensure_proxy: bool = True,
    height: int = 360,
    fps: float = 12.0,
) -> dict:
    """Cut a time range from the fresh scrub proxy (no full re-render).

    For focused review of one section after ensure_preview_proxy.
    """
    return _require_editor().preview_range(
        output_path,
        start_seconds,
        end_seconds,
        ensure_proxy=ensure_proxy,
        height=height,
        fps=fps,
    )


@mcp.tool()
def suggest_room_tone(path: str) -> dict:
    """Find a quiet donor segment in a take for room-tone / ambience fill."""
    return _require_editor().suggest_room_tone(path)


@mcp.tool()
def extract_room_tone(
    path: str,
    output_path: str,
    start: float | None = None,
    end: float | None = None,
    loop_to_seconds: float | None = None,
) -> dict:
    """Extract room-tone audio (optional loop) from a donor range."""
    return _require_editor().extract_room_tone(
        path,
        output_path,
        start=start,
        end=end,
        loop_to_seconds=loop_to_seconds,
    )


@mcp.tool()
def place_room_tone(
    source_path: str,
    track_id: str | None = None,
    start_frame: int = 0,
    loop_to_seconds: float | None = None,
    gain_db: float = -8.0,
) -> dict:
    """Extract room tone from source_path and place under the timeline.

    Fills digital silence after dialogue cuts. gain_db default -8.
    """
    return _require_editor().place_room_tone(
        source_path,
        track_id,
        start_frame=start_frame,
        loop_to_seconds=loop_to_seconds,
        gain_db=gain_db,
    )


@mcp.tool()
def export(
    output_path: str,
    normalize_preset: str | None = None,
    run_delivery_check: bool = True,
    delivery_preset: str = "streaming",
) -> dict:
    """Render the full timeline to a real video file at output_path.

    Optional normalize_preset (streaming/youtube/…) loudness-normalizes to a
    *_loud sibling and returns that path. When run_delivery_check (default
    true), includes delivery_check result — agent must not claim professional
    delivery if delivery_check.ok is false.
    """
    editor = _require_editor()
    written = editor.export(Path(output_path), normalize_preset=normalize_preset)
    result = _probe(written)
    payload: dict = {
        "path": str(written),
        "duration_seconds": result.duration_seconds,
        "fps": result.fps,
        "width": result.width,
        "height": result.height,
        "has_video": result.has_video,
        "has_audio": result.has_audio,
        "normalize_preset": normalize_preset,
    }
    if run_delivery_check:
        payload["delivery_check"] = editor.delivery_check(
            written, preset=delivery_preset,
        )
    return payload


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
