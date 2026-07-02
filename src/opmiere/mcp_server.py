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
      {"type": "text", "content": str, "position": "top"|"center"|"bottom" (default bottom), "size": int (default 48), "color": "white" (default), "font": optional path to a .ttf/.ttc (default is a CJK-capable font)}
      {"type": "blur", "amount": float (default 5.0, gaussian blur sigma - bigger is blurrier)}
      {"type": "vignette", "strength": float (default 1.0, bigger is a more visible dark-corner effect)}
    A fade's duration_frames must not exceed the clip's own duration_frames
    (visible in get_project_state). Chroma key / green-screen isn't
    supported yet - it needs multi-track compositing (a second layer to key
    onto), which the render backend doesn't have.
    """
    return _require_editor().apply_effect(clip_id, effect).to_dict()


@mcp.tool()
def add_transition(clip_id: str, transition_type: str, duration_frames: int) -> dict:
    """Dissolve clip_id in from whatever clip precedes it on its track.

    transition_type: currently only "cross_dissolve". The boundary must
    currently be a clean hard cut (this clip's start == the previous clip's
    end) - check get_project_state first. This shortens the combined
    timeline by duration_frames, since the two clips now overlap by that
    much instead of playing back to back.
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
