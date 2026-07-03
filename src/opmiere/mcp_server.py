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

from .generation import ComfyUIProvider
from .model import MediaKind, TrackKind
from .ops import Editor
from .render.probe import probe as _probe

mcp = FastMCP(
    name="opmiere",
    instructions=(
        "Opmiere is an agent-native video editor. Call create_project or "
        "open_project first. get_project_state shows the current timeline "
        "(track/clip/media ids) - call it whenever you need to see what "
        "exists before referencing an id. All positions and trims are in "
        "frames at the project's fps (see get_project_state). To add "
        "AI-generated media: generate() a job, poll job_status() until "
        "'done', then place_generated() to add it as a clip."
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
def import_media(src_path: str, kind: MediaKind) -> dict:
    """Copy a source file into the project and register it as media.

    kind: 'video' or 'audio' for now ('image' arrives with generation in P2).
    Every field is filled from a real ffprobe of the file, never guessed.
    """
    media = _require_editor().import_media(Path(src_path), kind)
    return media.to_dict()


@mcp.tool()
def add_track(kind: TrackKind) -> dict:
    """Add a new track ('video' or 'audio') to the timeline.

    Video tracks stack by creation order: the *first* video track is the
    base/background layer (clips must be contiguous from frame 0, like P0
    always required). Any video track added after it is an overlay layer,
    full-frame, shown only during its own clips' [start, end) windows -
    the base (or lower overlays) show through elsewhere, so overlay tracks
    are allowed gaps and don't need to start at frame 0. Clips on the same
    overlay track still can't overlap each other. No chroma-key/PiP sizing
    yet - overlay clips always cover the whole frame while active.
    """
    return _require_editor().add_track(kind).to_dict()


@mcp.tool()
def add_clip(track_id: str, media_id: str, start: int, src_in: int, src_out: int) -> dict:
    """Place the trimmed range [src_in, src_out) of media_id onto track_id at frame `start`."""
    return _require_editor().add_clip(track_id, media_id, start, src_in, src_out).to_dict()


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
    """Remove a clip from its track."""
    return _require_editor().delete_clip(clip_id).to_dict()


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
    previous clip's end) - check get_project_state first. This shortens the
    combined timeline by duration_frames, since the two clips now overlap by
    that much instead of playing back to back.
    """
    return _require_editor().add_transition(clip_id, transition_type, duration_frames).to_dict()


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

    kind="upscale": the "finish" half of the draft->finish workflow
      (ARCHITECTURE.md 5.7 D) as an alternative to re-running a full
      generation at a higher quality tier - a deterministic 4x super-
      resolution pass over an already-approved draft image (no seed/steps/
      cfg, so results are stable and it's cheap relative to a re-generate).
      prompt is ignored (pass ""); required param source_path - the local
      image file to upscale (typically a draft job's own result_path, after
      it passed quality_check and looked right on inspection). Only image
      is supported (not video) - see get_license_report for source
      RealESRGAN_x4plus (BSD-3-Clause, commercial-safe).
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
def export(output_path: str) -> dict:
    """Render the full timeline to a real video file at output_path.

    Returns ffprobe-verified facts about the file actually written — the
    agent should read these back rather than assume the export matched intent.
    """
    editor = _require_editor()
    written = editor.export(Path(output_path))
    result = _probe(written)
    return {
        "path": str(written),
        "duration_seconds": result.duration_seconds,
        "fps": result.fps,
        "width": result.width,
        "height": result.height,
        "has_video": result.has_video,
        "has_audio": result.has_audio,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
