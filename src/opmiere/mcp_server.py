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
        "frames at the project's fps (see get_project_state)."
    ),
)

_editor: Editor | None = None


def _require_editor() -> Editor:
    if _editor is None:
        raise RuntimeError("no project is open — call create_project or open_project first")
    return _editor


@mcp.tool()
def create_project(
    bundle_path: str, fps: float = 30.0, width: int = 1920, height: int = 1080
) -> dict:
    """Create a new .opm project bundle and make it the active project."""
    global _editor
    _editor = Editor.create(Path(bundle_path), fps=fps, width=width, height=height)
    return _editor.describe()


@mcp.tool()
def open_project(bundle_path: str) -> dict:
    """Open an existing .opm project bundle and make it the active project."""
    global _editor
    _editor = Editor.open(Path(bundle_path))
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
    """Add a new track ('video' or 'audio') to the timeline."""
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
    A fade's duration_frames must not exceed the clip's own duration_frames
    (visible in get_project_state).
    """
    return _require_editor().apply_effect(clip_id, effect).to_dict()


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
