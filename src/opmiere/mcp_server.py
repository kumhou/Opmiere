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
def move_clip(
    clip_id: str,
    new_start: int,
    follow_links: bool = False,
) -> dict:
    """Move a clip to a new timeline start frame. follow_links moves link group."""
    r = _require_editor().move_clip(
        clip_id, new_start, follow_links=follow_links,
    )
    if hasattr(r, "to_dict"):
        return r.to_dict()
    return r  # type: ignore[return-value]


@mcp.tool()
def trim_clip(clip_id: str, src_in: int, src_out: int) -> dict:
    """Change a clip's source in/out trim points (frames)."""
    return _require_editor().trim_clip(clip_id, src_in, src_out).to_dict()


@mcp.tool()
def set_clip_layout(
    clip_id: str,
    start: int | None = None,
    src_in: int | None = None,
    src_out: int | None = None,
) -> dict:
    """Atomic move+trim for UI/agent drag (one undo step)."""
    return _require_editor().set_clip_layout(
        clip_id, start=start, src_in=src_in, src_out=src_out,
    )


@mcp.tool()
def edge_trim(
    clip_id: str,
    edge: str,
    delta_frames: int,
    mode: str = "normal",
) -> dict:
    """Trim left/right edge by delta_frames (mode: normal|ripple)."""
    return _require_editor().edge_trim(
        clip_id, edge, delta_frames, mode=mode,
    )


@mcp.tool()
def refresh_preview_proxy(
    quick: bool = False,
    force: bool | None = None,
    height: int | None = None,
    fps: float | None = None,
) -> dict:
    """Rebuild timeline scrub proxy when stale (quick≈180p for snappy UI)."""
    return _require_editor().refresh_preview_proxy(
        quick=quick, force=force, height=height, fps=fps,
    )


@mcp.tool()
def set_clip_gain(clip_id: str, db: float) -> dict:
    """Set clip volume gain in dB (replaces prior gain effects). 0 = unity."""
    return _require_editor().set_clip_gain(clip_id, db)


@mcp.tool()
def waveform_peaks(
    clip_id: str | None = None,
    media_id: str | None = None,
    path: str | None = None,
    num_peaks: int = 200,
    use_cache: bool = True,
) -> dict:
    """Audio peak envelope [0..1] for timeline waveforms (cached per media)."""
    return _require_editor().waveform_peaks(
        path=path,
        media_id=media_id,
        clip_id=clip_id,
        num_peaks=num_peaks,
        use_cache=use_cache,
    )


@mcp.tool()
def media_thumbnail(
    media_id: str,
    time_seconds: float = 0.1,
    width: int = 160,
    force: bool = False,
) -> dict:
    """Poster frame for media bin (cached under analysis/thumbs/)."""
    return _require_editor().media_thumbnail(
        media_id, time_seconds=time_seconds, width=width, force=force,
    )


@mcp.tool()
def place_batch(
    paths: list[str],
    kind: str | None = None,
    track_id: str | None = None,
    start: int | None = None,
    sequential: bool = True,
    conform: bool = True,
    fit: str = "none",
    build_proxy: bool = False,
    image_duration_frames: int = 90,
) -> dict:
    """Import+place many files. kind=None auto-detects by suffix; sequential appends."""
    return _require_editor().place_batch(
        paths,
        kind=kind,  # type: ignore[arg-type]
        track_id=track_id,
        start=start,
        sequential=sequential,
        conform=conform,
        fit=fit,
        build_proxy=build_proxy,
        image_duration_frames=image_duration_frames,
    )


@mcp.tool()
def mix_view() -> dict:
    """Mix console: audio tracks, clip gains, ducking edges."""
    return _require_editor().mix_view()


@mcp.tool()
def list_cut_templates() -> dict:
    """Named first-cut recipes: talking_head, short_form, interview, vlog."""
    return _require_editor().list_cut_templates()


@mcp.tool()
def apply_cut_template(
    template: str,
    paths: list[str] | None = None,
    a_roll: list[str] | None = None,
    music: str | None = None,
    vo: str | None = None,
    style_override: str | None = None,
    dry_run: bool = False,
    build_proxy: bool = False,
    apply_silence: bool = False,
) -> dict:
    """Run a cut template: place media, apply style, optional duck; return hints.

    dry_run=true only returns the plan. paths auto-split video vs audio.
    apply_silence=true trims dead air on first A-roll when ≥2 keep islands.
    """
    return _require_editor().apply_cut_template(
        template,
        paths=paths,
        a_roll=a_roll,
        music=music,
        vo=vo,
        style_override=style_override,
        dry_run=dry_run,
        build_proxy=build_proxy,
        apply_silence=apply_silence,
    )


@mcp.tool()
def apply_silence_to_clip(
    clip_id: str,
    silence_threshold_db: float = -40.0,
    min_silence_seconds: float = 0.4,
    pad_seconds: float = 0.08,
    dry_run: bool = True,
) -> dict:
    """Silence keep-ranges on a clip; dry_run default. Applies only if ≥2 islands."""
    return _require_editor().apply_silence_to_clip(
        clip_id,
        silence_threshold_db=silence_threshold_db,
        min_silence_seconds=min_silence_seconds,
        pad_seconds=pad_seconds,
        dry_run=dry_run,
    )


@mcp.tool()
def finish_delivery(
    output_path: str,
    normalize_preset: str | None = "streaming",
    delivery_preset: str = "streaming",
    run_review: bool = True,
    run_sequence_sheet: bool = False,
    prepare: bool = True,
) -> dict:
    """prepare gaps + review + export + delivery_check. Honest ok / delivery_ok."""
    return _require_editor().finish_delivery(
        output_path,
        normalize_preset=normalize_preset,
        delivery_preset=delivery_preset,
        run_review=run_review,
        run_sequence_sheet=run_sequence_sheet,
        prepare=prepare,
    )


@mcp.tool()
def fill_track_gaps(
    track_id: str | None = None,
    mode: str = "slug",
) -> dict:
    """Fill base-track holes: slug=black/silence pads, close=pack left."""
    return _require_editor().fill_track_gaps(track_id, mode=mode)


@mcp.tool()
def prepare_export(fill_video: bool = True, fill_audio: bool = False) -> dict:
    """Slug-pad base tracks so freeform timeline still exports."""
    return _require_editor().prepare_export(
        fill_video=fill_video, fill_audio=fill_audio,
    )


@mcp.tool()
def add_marker(
    frame: int | None = None,
    time_seconds: float | None = None,
    label: str = "",
    color: str = "#7c9cff",
) -> dict:
    """Add a timeline marker at frame or time_seconds."""
    return _require_editor().add_marker(
        frame, time_seconds=time_seconds, label=label, color=color,
    )


@mcp.tool()
def delete_marker(marker_id: str) -> dict:
    return _require_editor().delete_marker(marker_id)


@mcp.tool()
def list_markers() -> dict:
    return _require_editor().list_markers()


@mcp.tool()
def split_all_at(at_frame: int, track_ids: list[str] | None = None) -> dict:
    """Razor: split every clip containing at_frame (all tracks or track_ids)."""
    return _require_editor().split_all_at(at_frame, track_ids=track_ids)


@mcp.tool()
def link_transition(
    right_clip_id: str,
    transition_type: str = "cross_dissolve",
    duration_frames: int = 12,
    left_clip_id: str | None = None,
) -> dict:
    """Crossfade into right_clip from previous hard-cut neighbor."""
    return _require_editor().link_transition(
        right_clip_id,
        transition_type=transition_type,
        duration_frames=duration_frames,
        left_clip_id=left_clip_id,
    )


@mcp.tool()
def snap_points(include_markers: bool = True) -> dict:
    """Clip edge / marker frames for UI snap."""
    return _require_editor().snap_points(include_markers=include_markers)


@mcp.tool()
def copy_clip(clip_id: str) -> dict:
    """Copy clip to session clipboard."""
    return _require_editor().copy_clip(clip_id)


@mcp.tool()
def paste_clip(
    track_id: str | None = None,
    start: int | None = None,
    playhead_frame: int | None = None,
    mode: str = "insert",
) -> dict:
    """Paste clipboard. mode=insert|overwrite (overwrite lifts range first)."""
    return _require_editor().paste_clip(
        track_id=track_id,
        start=start,
        at_playhead=playhead_frame is not None,
        playhead_frame=playhead_frame,
        mode=mode,
    )


@mcp.tool()
def duplicate_clip(clip_id: str, offset_frames: int | None = None) -> dict:
    """Duplicate clip after itself (or at start+offset)."""
    return _require_editor().duplicate_clip(clip_id, offset_frames=offset_frames)


@mcp.tool()
def set_in_point(frame: int | None = None, time_seconds: float | None = None) -> dict:
    """Set work-area In point (session)."""
    return _require_editor().set_in_point(frame, time_seconds=time_seconds)


@mcp.tool()
def set_out_point(frame: int | None = None, time_seconds: float | None = None) -> dict:
    """Set work-area Out point (session)."""
    return _require_editor().set_out_point(frame, time_seconds=time_seconds)


@mcp.tool()
def clear_in_out() -> dict:
    return _require_editor().clear_in_out()


@mcp.tool()
def get_in_out() -> dict:
    return _require_editor().get_in_out()


@mcp.tool()
def export_work_area(
    output_path: str,
    normalize_preset: str | None = "streaming",
    run_delivery_check: bool = True,
) -> dict:
    """Export [in, out) work area after set_in_point / set_out_point."""
    return _require_editor().export_work_area(
        output_path,
        normalize_preset=normalize_preset,
        run_delivery_check=run_delivery_check,
    )


@mcp.tool()
def set_track_muted(track_id: str, muted: bool = True) -> dict:
    return _require_editor().set_track_muted(track_id, muted)


@mcp.tool()
def set_track_solo(
    track_id: str,
    solo: bool = True,
    exclusive: bool = False,
) -> dict:
    """Solo track. exclusive=True clears solo on other same-kind tracks."""
    return _require_editor().set_track_solo(
        track_id, solo, exclusive=exclusive,
    )


@mcp.tool()
def set_track_locked(track_id: str, locked: bool = True) -> dict:
    """Lock track against layout edits."""
    return _require_editor().set_track_locked(track_id, locked)


@mcp.tool()
def set_clip_muted(clip_id: str, muted: bool = True) -> dict:
    """Mute clip (black/silence in export; keeps timeline duration)."""
    return _require_editor().set_clip_muted(clip_id, muted)


@mcp.tool()
def nudge_clips(
    clip_ids: list[str],
    delta_frames: int,
    follow_links: bool = True,
) -> dict:
    """Move many clips by delta_frames (one undo). follow_links expands groups."""
    return _require_editor().nudge_clips(
        clip_ids, delta_frames, follow_links=follow_links,
    )


@mcp.tool()
def set_clips_muted(clip_ids: list[str], muted: bool = True) -> dict:
    """Mute/unmute many clips."""
    return _require_editor().set_clips_muted(clip_ids, muted)


@mcp.tool()
def delete_clips(
    clip_ids: list[str],
    ripple: bool = False,
    follow_links: bool = True,
) -> dict:
    """Delete many clips; ripple=true closes holes; follow_links expands groups."""
    return _require_editor().delete_clips(
        clip_ids, ripple=ripple, follow_links=follow_links,
    )


@mcp.tool()
def link_clips(clip_ids: list[str], group_id: str | None = None) -> dict:
    """Link clips into one selection group (A/V pairs etc.)."""
    return _require_editor().link_clips(clip_ids, group_id=group_id)


@mcp.tool()
def unlink_clips(clip_ids: list[str] | None = None) -> dict:
    """Clear link_group on given clips (or all if omitted)."""
    return _require_editor().unlink_clips(clip_ids)


@mcp.tool()
def linked_group(clip_id: str) -> dict:
    """List all clips in the same link_group as clip_id."""
    return _require_editor().linked_group(clip_id)


@mcp.tool()
def frames_to_tc(frame: int) -> dict:
    """Format frame as HH:MM:SS:FF."""
    return _require_editor().frames_to_tc(frame)


@mcp.tool()
def tc_to_frames(tc: str) -> dict:
    """Parse HH:MM:SS:FF or seconds into frame index."""
    return _require_editor().tc_to_frames(tc)


@mcp.tool()
def ripple_nudge(clip_id: str, delta_frames: int, include_self: bool = True) -> dict:
    """Move clip + all later clips on same track (magnetic-style)."""
    return _require_editor().ripple_nudge(
        clip_id, delta_frames, include_self=include_self,
    )


@mcp.tool()
def insert_time(track_id: str, at_frame: int, frames: int) -> dict:
    """Open a hole: push clips at/after at_frame to the right."""
    return _require_editor().insert_time(track_id, at_frame, frames)


@mcp.tool()
def insert_edit(
    media_id: str,
    track_id: str,
    at_frame: int,
    src_in: int = 0,
    src_out: int | None = None,
    ripple: bool = True,
    name: str | None = None,
) -> dict:
    """Classic insert edit: place media and ripple later clips right."""
    return _require_editor().insert_edit(
        media_id,
        track_id,
        at_frame,
        src_in=src_in,
        src_out=src_out,
        ripple=ripple,
        name=name,
    )


@mcp.tool()
def overwrite_edit(
    media_id: str,
    track_id: str,
    at_frame: int,
    src_in: int = 0,
    src_out: int | None = None,
    name: str | None = None,
) -> dict:
    """Classic overwrite: lift [at, at+dur) then place media."""
    return _require_editor().overwrite_edit(
        media_id,
        track_id,
        at_frame,
        src_in=src_in,
        src_out=src_out,
        name=name,
    )


@mcp.tool()
def three_point_edit(
    media_id: str,
    track_id: str,
    mode: str = "overwrite",
    fit: str = "stretch",
    src_in: int = 0,
    src_out: int | None = None,
    name: str | None = None,
) -> dict:
    """Three-point edit: place media into work area [in, out)."""
    return _require_editor().three_point_edit(
        media_id,
        track_id,
        mode=mode,
        fit=fit,
        src_in=src_in,
        src_out=src_out,
        name=name,
    )


@mcp.tool()
def media_usage_report() -> dict:
    """Per-media usage: clip counts and timeline frames."""
    return _require_editor().media_usage_report()


@mcp.tool()
def apply_effects_to_track(
    track_id: str,
    effects: list[dict],
    replace_types: bool = True,
) -> dict:
    """Apply one or more effects to every clip on a track."""
    return _require_editor().apply_effects_to_track(
        track_id, effects, replace_types=replace_types,
    )


@mcp.tool()
def clear_effects(
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
    types: list[str] | None = None,
) -> dict:
    """Clear effects on clip selection or whole track."""
    return _require_editor().clear_effects(
        clip_ids, track_id=track_id, types=types,
    )


@mcp.tool()
def extract_time(
    track_id: str,
    start_frame: int,
    end_frame: int,
    ripple: bool = True,
) -> dict:
    """Lift [start, end) on one track; ripple pulls later clips left."""
    return _require_editor().extract_time(
        track_id, start_frame, end_frame, ripple=ripple,
    )


@mcp.tool()
def set_clip_meta(
    clip_id: str,
    name: str | None = None,
    color: str | None = None,
    clear_name: bool = False,
    clear_color: bool = False,
) -> dict:
    """Set clip display name / color chip (UI only)."""
    return _require_editor().set_clip_meta(
        clip_id, name=name, color=color,
        clear_name=clear_name, clear_color=clear_color,
    )


@mcp.tool()
def list_clip_colors() -> dict:
    return _require_editor().list_clip_colors()


@mcp.tool()
def list_recent_projects(limit: int = 12) -> dict:
    """Recently opened .opm bundles (user config, not project-local)."""
    return _require_editor().list_recent_projects(limit=limit)


@mcp.tool()
def set_autosave(enabled: bool = True) -> dict:
    """When true, save project after every successful mutation."""
    return _require_editor().set_autosave(enabled)


@mcp.tool()
def project_dirty() -> dict:
    return {
        "dirty": _require_editor().is_dirty(),
        "autosave": _require_editor()._autosave,
        "bundle_path": str(_require_editor().bundle.root),
    }


@mcp.tool()
def set_project_notes(notes: str) -> dict:
    """Persist free-text project notes (not burned into export)."""
    return _require_editor().set_project_notes(notes)


@mcp.tool()
def get_project_notes() -> dict:
    return _require_editor().get_project_notes()


@mcp.tool()
def get_keymap_help() -> dict:
    """Web NLE keyboard shortcuts (for agents / help UI)."""
    return _require_editor().get_keymap_help()


@mcp.tool()
def freeze_frame(
    clip_id: str,
    at_timeline_frame: int | None = None,
    duration_frames: int = 30,
    track_id: str | None = None,
    start: int | None = None,
) -> dict:
    """Hold a still frame extracted from a video clip as a new image clip."""
    return _require_editor().freeze_frame(
        clip_id,
        at_timeline_frame=at_timeline_frame,
        duration_frames=duration_frames,
        track_id=track_id,
        start=start,
    )


@mcp.tool()
def reverse_clip(clip_id: str, replace: bool = True) -> dict:
    """Re-encode clip source range reversed; replace clip media by default."""
    return _require_editor().reverse_clip(clip_id, replace=replace)


@mcp.tool()
def stabilize_clip(
    clip_id: str,
    replace: bool = True,
    strength: float = 1.0,
) -> dict:
    """Re-encode with deshake (video). strength scales rx/ry ~0.25–2."""
    return _require_editor().stabilize_clip(
        clip_id, replace=replace, strength=strength,
    )


@mcp.tool()
def export_markers(
    path: str | None = None,
    format: str = "youtube",
) -> dict:
    """Export markers as youtube chapters, csv, or json."""
    return _require_editor().export_markers(path, format=format)


@mcp.tool()
def copy_attributes(clip_id: str) -> dict:
    """Copy speed/position/gain/fades/opacity to session attributes clipboard."""
    return _require_editor().copy_attributes(clip_id)


@mcp.tool()
def paste_attributes(
    clip_id: str,
    speed: bool = True,
    position: bool = True,
    gain: bool = True,
    opacity: bool = True,
    fades: bool = True,
) -> dict:
    """Paste attributes clipboard onto a clip."""
    return _require_editor().paste_attributes(
        clip_id,
        speed=speed,
        position=position,
        gain=gain,
        opacity=opacity,
        fades=fades,
    )


@mcp.tool()
def trim_to_playhead(
    clip_id: str,
    playhead_frame: int,
    edge: str = "head",
    mode: str = "ripple",
    follow_links: bool = False,
) -> dict:
    """Trim head (Q) or tail (W) to playhead. follow_links trims A/V peers."""
    return _require_editor().trim_to_playhead(
        clip_id,
        playhead_frame,
        edge=edge,
        mode=mode,
        follow_links=follow_links,
    )


@mcp.tool()
def import_markers(
    text: str,
    format: str = "youtube",
    replace: bool = False,
    default_color: str = "#7c9cff",
) -> dict:
    """Import markers from YouTube chapter text or CSV."""
    return _require_editor().import_markers(
        text, format=format, replace=replace, default_color=default_color,
    )


@mcp.tool()
def export_edl(path: str | None = None, title: str | None = None) -> dict:
    """Export simple CMX-style EDL of the first video track."""
    return _require_editor().export_edl(path, title=title)


@mcp.tool()
def describe_clip(clip_id: str) -> dict:
    """Rich clip card: layout, media, track, link peers."""
    return _require_editor().describe_clip(clip_id)


@mcp.tool()
def search_clips(
    query: str,
    track_id: str | None = None,
    kind: str | None = None,
) -> dict:
    """Search clips by name/path/id/color substring."""
    return _require_editor().search_clips(
        query, track_id=track_id, kind=kind,
    )


@mcp.tool()
def clips_in_range(
    start_frame: int,
    end_frame: int,
    track_id: str | None = None,
    kind: str | None = None,
    partial: bool = True,
) -> dict:
    """List clips overlapping [start_frame, end_frame)."""
    return _require_editor().clips_in_range(
        start_frame,
        end_frame,
        track_id=track_id,
        kind=kind,
        partial=partial,
    )


@mcp.tool()
def fit_to_fill(
    clip_id: str,
    end_frame: int | None = None,
    clamp: bool = True,
) -> dict:
    """Rate-stretch clip to end_frame (or next clip start)."""
    return _require_editor().fit_to_fill(
        clip_id, end_frame=end_frame, clamp=clamp,
    )


@mcp.tool()
def replace_edit(
    clip_id: str,
    media_id: str,
    mode: str = "stretch",
) -> dict:
    """Replace clip media; stretch|trim_end|trim_start|full."""
    return _require_editor().replace_edit(clip_id, media_id, mode=mode)


@mcp.tool()
def copy_to_track(
    clip_id: str,
    track_id: str,
    start: int | None = None,
    copy_effects: bool = True,
    copy_link: bool = False,
) -> dict:
    """Clone clip onto another same-kind track."""
    return _require_editor().copy_to_track(
        clip_id,
        track_id,
        start=start,
        copy_effects=copy_effects,
        copy_link=copy_link,
    )


@mcp.tool()
def rename_clips(
    pattern: str,
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
) -> dict:
    """Batch rename. Tokens: {n} {nn} {name} {media} {id} {track}."""
    return _require_editor().rename_clips(
        pattern, clip_ids=clip_ids, track_id=track_id,
    )


@mcp.tool()
def import_edl(
    text: str | None = None,
    path: str | None = None,
    track_id: str | None = None,
    replace_track: bool = False,
    media_map: dict[str, str] | None = None,
) -> dict:
    """Import simple CMX EDL; media must already be in the project bin."""
    return _require_editor().import_edl(
        text,
        path=path,
        track_id=track_id,
        replace_track=replace_track,
        media_map=media_map,
    )


@mcp.tool()
def lift(
    start_frame: int,
    end_frame: int,
    track_id: str | None = None,
    track_ids: list[str] | None = None,
    kind: str | None = None,
) -> dict:
    """Lift range leaving gap (no ripple). Optional track filters."""
    return _require_editor().lift(
        start_frame,
        end_frame,
        track_id=track_id,
        track_ids=track_ids,
        kind=kind,
    )


@mcp.tool()
def split_at_markers(
    track_ids: list[str] | None = None,
    marker_ids: list[str] | None = None,
) -> dict:
    """Razor tracks at each marker frame (one undo)."""
    return _require_editor().split_at_markers(
        track_ids=track_ids, marker_ids=marker_ids,
    )


@mcp.tool()
def match_duration(
    clip_id: str,
    reference_clip_id: str,
    clamp: bool = True,
) -> dict:
    """Stretch clip_id to match reference_clip_id timeline duration."""
    return _require_editor().match_duration(
        clip_id, reference_clip_id, clamp=clamp,
    )


@mcp.tool()
def set_clips_color(clip_ids: list[str], color: str | None = None) -> dict:
    """Batch set/clear color chips. color=None clears."""
    return _require_editor().set_clips_color(clip_ids, color)


@mcp.tool()
def clips_by_color(
    color: str,
    track_id: str | None = None,
    kind: str | None = None,
) -> dict:
    """Find clips with matching color chip."""
    return _require_editor().clips_by_color(
        color, track_id=track_id, kind=kind,
    )


@mcp.tool()
def export_cutlist(
    path: str | None = None,
    format: str = "csv",
    track_id: str | None = None,
) -> dict:
    """Export cut list as csv or json."""
    return _require_editor().export_cutlist(
        path, format=format, track_id=track_id,
    )


@mcp.tool()
def place_media(
    media_id: str,
    track_id: str,
    start: int,
    src_in: int | None = None,
    src_out: int | None = None,
    mode: str = "insert",
    name: str | None = None,
) -> dict:
    """Place bin media on track; mode insert|overwrite."""
    return _require_editor().place_media(
        media_id,
        track_id,
        start,
        src_in=src_in,
        src_out=src_out,
        mode=mode,
        name=name,
    )


@mcp.tool()
def join_clips(clip_id_a: str, clip_id_b: str) -> dict:
    """Merge two adjacent same-media clips on one track."""
    return _require_editor().join_clips(clip_id_a, clip_id_b)


@mcp.tool()
def set_clips_speed(clip_ids: list[str], speed: float) -> dict:
    """Batch set speed in [0.25, 4]."""
    return _require_editor().set_clips_speed(clip_ids, speed)


@mcp.tool()
def trim_to_range(
    clip_id: str,
    start_frame: int,
    end_frame: int,
    mode: str = "normal",
) -> dict:
    """Trim clip to timeline range [start, end). mode normal|ripple."""
    return _require_editor().trim_to_range(
        clip_id, start_frame, end_frame, mode=mode,
    )


@mcp.tool()
def auto_link_av(
    tolerance_frames: int = 0,
    track_id_video: str | None = None,
    track_id_audio: str | None = None,
) -> dict:
    """Link unlinked V/A pairs that share the same start."""
    return _require_editor().auto_link_av(
        tolerance_frames=tolerance_frames,
        track_id_video=track_id_video,
        track_id_audio=track_id_audio,
    )


@mcp.tool()
def set_clips_meta(
    clip_ids: list[str],
    name: str | None = None,
    color: str | None = None,
    clear_name: bool = False,
    clear_color: bool = False,
) -> dict:
    """Batch name/color meta."""
    return _require_editor().set_clips_meta(
        clip_ids,
        name=name,
        color=color,
        clear_name=clear_name,
        clear_color=clear_color,
    )


@mcp.tool()
def stagger_clips(clip_ids: list[str], offset_frames: int) -> dict:
    """Offset clips by index * offset_frames."""
    return _require_editor().stagger_clips(clip_ids, offset_frames)


@mcp.tool()
def reverse_track_order(track_id: str, pack_from: int = 0) -> dict:
    """Reverse clip order on a track and repack."""
    return _require_editor().reverse_track_order(track_id, pack_from=pack_from)


@mcp.tool()
def clear_transitions(
    track_id: str | None = None,
    clip_ids: list[str] | None = None,
) -> dict:
    """Remove transition_in and restore hard-cut starts."""
    return _require_editor().clear_transitions(
        track_id=track_id, clip_ids=clip_ids,
    )


@mcp.tool()
def set_clips_fades(
    clip_ids: list[str],
    fade_in_frames: int | None = None,
    fade_out_frames: int | None = None,
) -> dict:
    """Batch fade in/out frames."""
    return _require_editor().set_clips_fades(
        clip_ids,
        fade_in_frames=fade_in_frames,
        fade_out_frames=fade_out_frames,
    )


@mcp.tool()
def append_media(
    media_id: str,
    track_id: str,
    src_in: int | None = None,
    src_out: int | None = None,
    name: str | None = None,
) -> dict:
    """Place media after last clip on track."""
    return _require_editor().append_media(
        media_id, track_id, src_in=src_in, src_out=src_out, name=name,
    )


@mcp.tool()
def duplicate_range(
    start_frame: int,
    end_frame: int,
    track_id: str,
    dest_start: int | None = None,
    dest_track_id: str | None = None,
) -> dict:
    """Copy overlapping clips in range to dest start."""
    return _require_editor().duplicate_range(
        start_frame,
        end_frame,
        track_id=track_id,
        dest_start=dest_start,
        dest_track_id=dest_track_id,
    )


@mcp.tool()
def move_block(
    clip_ids: list[str],
    to_frame: int,
    follow_links: bool = False,
) -> dict:
    """Move selection as rigid block so leftmost starts at to_frame."""
    return _require_editor().move_block(
        clip_ids, to_frame, follow_links=follow_links,
    )


@mcp.tool()
def set_clips_gain(clip_ids: list[str], db: float) -> dict:
    """Batch set gain dB."""
    return _require_editor().set_clips_gain(clip_ids, db)


@mcp.tool()
def set_clips_opacity(clip_ids: list[str], amount: float) -> dict:
    """Batch set opacity 0..1."""
    return _require_editor().set_clips_opacity(clip_ids, amount)


@mcp.tool()
def validate_timeline(track_id: str | None = None) -> dict:
    """Report gaps/overlaps/transition issues (read-only)."""
    return _require_editor().validate_timeline(track_id=track_id)


@mcp.tool()
def extract_range(
    start_frame: int,
    end_frame: int,
    track_id: str | None = None,
    track_ids: list[str] | None = None,
    kind: str | None = None,
    ripple: bool = True,
) -> dict:
    """Extract range on one/many tracks; ripple closes gap by default."""
    return _require_editor().extract_range(
        start_frame,
        end_frame,
        track_id=track_id,
        track_ids=track_ids,
        kind=kind,
        ripple=ripple,
    )


@mcp.tool()
def apply_transitions_on_cuts(
    track_id: str,
    transition_type: str = "cross_dissolve",
    duration_frames: int = 15,
    max_count: int | None = None,
) -> dict:
    """Add same transition on every hard cut on a track."""
    return _require_editor().apply_transitions_on_cuts(
        track_id,
        transition_type=transition_type,
        duration_frames=duration_frames,
        max_count=max_count,
    )


@mcp.tool()
def list_media_status() -> dict:
    """Online/offline media census."""
    return _require_editor().list_media_status()


@mcp.tool()
def name_clips_from_media(
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
    strip_ext: bool = True,
) -> dict:
    """Set clip names from media basenames."""
    return _require_editor().name_clips_from_media(
        clip_ids, track_id=track_id, strip_ext=strip_ext,
    )


@mcp.tool()
def snap_clip(clip_id: str, to: str = "prev_end") -> dict:
    """Snap clip start: prev_end|next_start|zero."""
    return _require_editor().snap_clip(clip_id, to=to)


@mcp.tool()
def split_at_beats(
    track_id: str,
    media_id: str | None = None,
    path: str | None = None,
    max_splits: int = 64,
) -> dict:
    """Razor track at detected beat frames."""
    return _require_editor().split_at_beats(
        track_id, media_id=media_id, path=path, max_splits=max_splits,
    )


@mcp.tool()
def markers_from_beats(
    media_id: str | None = None,
    path: str | None = None,
    max_markers: int = 128,
    label_prefix: str = "Beat",
    color: str = "#e91e63",
    clear_existing_prefix: bool = False,
) -> dict:
    """Place timeline markers at detected beat frames (music grid, no razor).

    Use split_at_markers afterward if you want cuts on the beat grid.
    """
    return _require_editor().markers_from_beats(
        media_id,
        path=path,
        max_markers=max_markers,
        label_prefix=label_prefix,
        color=color,
        clear_existing_prefix=clear_existing_prefix,
    )


@mcp.tool()
def beat_grid(
    track_id: str | None = None,
    media_id: str | None = None,
    path: str | None = None,
    mode: str = "markers",
    max_beats: int = 128,
    label_prefix: str = "Beat",
    color: str = "#e91e63",
    clear_existing_prefix: bool = True,
    snap_clip_ids: list[str] | None = None,
) -> dict:
    """One-shot music cut grid.

    mode: markers | split | both | markers_snap
    both = markers + razor track; markers_snap = markers + snap clips.
    """
    return _require_editor().beat_grid(
        track_id,
        media_id,
        path=path,
        mode=mode,
        max_beats=max_beats,
        label_prefix=label_prefix,
        color=color,
        clear_existing_prefix=clear_existing_prefix,
        snap_clip_ids=snap_clip_ids,
    )


@mcp.tool()
def markers_from_scenes(
    media_id: str | None = None,
    path: str | None = None,
    threshold: float = 27.0,
    min_scene_len: int = 15,
    backend: str = "auto",
    max_markers: int = 128,
    label_prefix: str = "Scene",
    color: str = "#ff9800",
    clear_existing_prefix: bool = False,
    include_start: bool = False,
) -> dict:
    """Detect shot boundaries and place timeline markers."""
    return _require_editor().markers_from_scenes(
        media_id,
        path=path,
        threshold=threshold,
        min_scene_len=min_scene_len,
        backend=backend,
        max_markers=max_markers,
        label_prefix=label_prefix,
        color=color,
        clear_existing_prefix=clear_existing_prefix,
        include_start=include_start,
    )


@mcp.tool()
def scene_grid(
    track_id: str | None = None,
    media_id: str | None = None,
    path: str | None = None,
    mode: str = "markers",
    threshold: float = 27.0,
    min_scene_len: int = 15,
    backend: str = "auto",
    max_scenes: int = 128,
    label_prefix: str = "Scene",
    color: str = "#ff9800",
    clear_existing_prefix: bool = True,
) -> dict:
    """One-shot scene grid: markers | split | both."""
    return _require_editor().scene_grid(
        track_id,
        media_id,
        path=path,
        mode=mode,
        threshold=threshold,
        min_scene_len=min_scene_len,
        backend=backend,
        max_scenes=max_scenes,
        label_prefix=label_prefix,
        color=color,
        clear_existing_prefix=clear_existing_prefix,
    )


@mcp.tool()
def apply_transitions_near_markers(
    track_id: str,
    transition_type: str = "cross_dissolve",
    duration_frames: int = 12,
    max_delta_frames: int = 2,
    max_count: int | None = None,
    marker_ids: list[str] | None = None,
) -> dict:
    """Add transitions only on hard cuts near timeline markers."""
    return _require_editor().apply_transitions_near_markers(
        track_id,
        transition_type=transition_type,
        duration_frames=duration_frames,
        max_delta_frames=max_delta_frames,
        max_count=max_count,
        marker_ids=marker_ids,
    )


@mcp.tool()
def place_media_at_markers(
    media_ids: list[str],
    track_id: str,
    marker_ids: list[str] | None = None,
    duration_frames: int | None = None,
    mode: str = "overwrite",
    cycle: bool = True,
) -> dict:
    """Place bin media at each timeline marker (music B-roll grid).

    media_ids cycle across markers when cycle=True. duration_frames=None uses
    media length clamped to next marker gap.
    """
    return _require_editor().place_media_at_markers(
        media_ids,
        track_id,
        marker_ids=marker_ids,
        duration_frames=duration_frames,
        mode=mode,
        cycle=cycle,
    )


@mcp.tool()
def fit_clips_to_markers(
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
    method: str = "speed",
    max_start_delta: int = 8,
    clamp: bool = True,
    marker_ids: list[str] | None = None,
) -> dict:
    """Stretch/trim clips so each fills to the next marker slot.

    method: speed | trim. Clip starts must be near a marker.
    """
    return _require_editor().fit_clips_to_markers(
        clip_ids,
        track_id,
        method=method,
        max_start_delta=max_start_delta,
        clamp=clamp,
        marker_ids=marker_ids,
    )


@mcp.tool()
def music_broll(
    track_id: str,
    media_ids: list[str],
    beat_media_id: str | None = None,
    beat_path: str | None = None,
    max_beats: int = 64,
    place_duration_frames: int | None = None,
    fit_method: str = "speed",
    transition: str | None = "cross_dissolve",
    transition_frames: int = 8,
    clear_beat_markers: bool = True,
) -> dict:
    """One-shot music B-roll: beats → place → fit → dissolves.

    Prefer this for agent music-video assembly on an overlay track.
    """
    return _require_editor().music_broll(
        track_id,
        media_ids,
        beat_media_id=beat_media_id,
        beat_path=beat_path,
        max_beats=max_beats,
        place_duration_frames=place_duration_frames,
        fit_method=fit_method,
        transition=transition,
        transition_frames=transition_frames,
        clear_beat_markers=clear_beat_markers,
    )


@mcp.tool()
def list_marker_slots(
    include_tail: bool = True,
    min_duration_frames: int = 1,
    marker_ids: list[str] | None = None,
) -> dict:
    """List marker-to-marker slots (frames/seconds) for B-roll planning."""
    return _require_editor().list_marker_slots(
        marker_ids=marker_ids,
        include_tail=include_tail,
        min_duration_frames=min_duration_frames,
    )


@mcp.tool()
def clear_markers(
    prefix: str | None = None,
    marker_ids: list[str] | None = None,
) -> dict:
    """Delete markers: all, by prefix, or by id list."""
    return _require_editor().clear_markers(prefix=prefix, marker_ids=marker_ids)


@mcp.tool()
def markers_from_srt(
    path: str | None = None,
    text: str | None = None,
    label_from_text: bool = True,
    max_label_len: int = 48,
    color: str = "#4caf50",
    clear_existing: bool = False,
    prefix: str = "",
) -> dict:
    """Import SRT cue starts as timeline markers (captions → chapters)."""
    return _require_editor().markers_from_srt(
        path,
        text=text,
        label_from_text=label_from_text,
        max_label_len=max_label_len,
        color=color,
        clear_existing=clear_existing,
        prefix=prefix,
    )


@mcp.tool()
def export_marker_segments(
    output_dir: str,
    name_prefix: str = "seg",
    include_tail: bool = True,
    min_duration_frames: int = 3,
    marker_ids: list[str] | None = None,
    filename_from_label: bool = True,
) -> dict:
    """Export one MP4 per marker-to-marker range (social chapter cuts).

    One full timeline encode, then ffmpeg trim per segment into output_dir.
    """
    return _require_editor().export_marker_segments(
        output_dir,
        name_prefix=name_prefix,
        include_tail=include_tail,
        min_duration_frames=min_duration_frames,
        marker_ids=marker_ids,
        filename_from_label=filename_from_label,
    )


@mcp.tool()
def export_track_stems(
    output_dir: str,
    track_ids: list[str] | None = None,
    kind: str | None = None,
    name_prefix: str = "stem",
    audio_only: bool = False,
) -> dict:
    """Export each track soloed (VO/music stems). Restores mute state."""
    return _require_editor().export_track_stems(
        output_dir,
        track_ids=track_ids,
        kind=kind,
        name_prefix=name_prefix,
        audio_only=audio_only,
    )


@mcp.tool()
def balance_clip_gains(
    clip_ids: list[str],
    target_db: float = 0.0,
    relative: bool = True,
) -> dict:
    """Balance clip gains (relative shift or absolute target_db)."""
    return _require_editor().balance_clip_gains(
        clip_ids, target_db=target_db, relative=relative,
    )


@mcp.tool()
def match_grade_to_clip(
    source_clip_id: str,
    target_clip_ids: list[str],
    replace: bool = True,
    effect_types: list[str] | None = None,
) -> dict:
    """Copy grade effects from one hero clip onto many targets."""
    return _require_editor().match_grade_to_clip(
        source_clip_id,
        target_clip_ids,
        replace=replace,
        effect_types=effect_types,
    )


@mcp.tool()
def sequence_from_media(
    media_ids: list[str],
    track_id: str,
    start_frame: int = 0,
    clear_track: bool = False,
    transition: str | None = None,
    transition_frames: int = 12,
    name_from_media: bool = True,
) -> dict:
    """Assemble bin media end-to-end on a track (first rough cut)."""
    return _require_editor().sequence_from_media(
        media_ids,
        track_id,
        start_frame=start_frame,
        clear_track=clear_track,
        transition=transition,
        transition_frames=transition_frames,
        name_from_media=name_from_media,
    )


@mcp.tool()
def assemble_unused_media(
    track_id: str,
    kind: str = "video",
    start_frame: int = 0,
    clear_track: bool = False,
    transition: str | None = None,
    transition_frames: int = 12,
) -> dict:
    """Place all unused bin media of a kind as an assembly sequence."""
    return _require_editor().assemble_unused_media(
        track_id,
        kind=kind,
        start_frame=start_frame,
        clear_track=clear_track,
        transition=transition,
        transition_frames=transition_frames,
    )


@mcp.tool()
def rough_cut(
    track_id: str,
    media_ids: list[str] | None = None,
    use_unused: bool = True,
    kind: str = "video",
    start_frame: int = 0,
    clear_track: bool = False,
    transition: str | None = "cross_dissolve",
    transition_frames: int = 10,
    apply_edge_fades: bool = True,
    fade_frames: int = 6,
) -> dict:
    """One-shot rough cut: sequence + dissolves + edge fades."""
    return _require_editor().rough_cut(
        track_id,
        media_ids=media_ids,
        use_unused=use_unused,
        kind=kind,
        start_frame=start_frame,
        clear_track=clear_track,
        transition=transition,
        transition_frames=transition_frames,
        apply_edge_fades=apply_edge_fades,
        fade_frames=fade_frames,
    )


@mcp.tool()
def apply_edge_fades(
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
    fade_in_frames: int = 6,
    fade_out_frames: int = 6,
    replace: bool = True,
) -> dict:
    """Add fade-in/out on clips (ids or whole track)."""
    return _require_editor().apply_edge_fades(
        clip_ids=clip_ids,
        track_id=track_id,
        fade_in_frames=fade_in_frames,
        fade_out_frames=fade_out_frames,
        replace=replace,
    )


@mcp.tool()
def setup_vo_music_duck(
    vo_track_id: str | None = None,
    music_track_id: str | None = None,
    threshold_db: float = -30.0,
    ratio: float = 8.0,
    attack_ms: float = 20.0,
    release_ms: float = 300.0,
    makeup_db: float = 0.0,
    music_gain_db: float | None = -6.0,
) -> dict:
    """Auto-wire music-under-VO ducking (picks tracks by name if omitted)."""
    return _require_editor().setup_vo_music_duck(
        vo_track_id=vo_track_id,
        music_track_id=music_track_id,
        threshold_db=threshold_db,
        ratio=ratio,
        attack_ms=attack_ms,
        release_ms=release_ms,
        makeup_db=makeup_db,
        music_gain_db=music_gain_db,
    )


@mcp.tool()
def freeze_at_markers(
    track_id: str,
    duration_frames: int = 24,
    marker_ids: list[str] | None = None,
    place_track_id: str | None = None,
) -> dict:
    """Freeze the clip under each marker as a still hold."""
    return _require_editor().freeze_at_markers(
        track_id,
        duration_frames=duration_frames,
        marker_ids=marker_ids,
        place_track_id=place_track_id,
    )


@mcp.tool()
def stills_at_markers(
    output_dir: str,
    width: int = 1280,
    marker_ids: list[str] | None = None,
    name_prefix: str = "still",
) -> dict:
    """Export a JPG still at each marker frame."""
    return _require_editor().stills_at_markers(
        output_dir,
        width=width,
        marker_ids=marker_ids,
        name_prefix=name_prefix,
    )


@mcp.tool()
def create_title_card(
    content: str,
    track_id: str,
    start_frame: int = 0,
    duration_frames: int = 90,
    position: str = "center",
    size: int = 64,
    border_width: int = 2,
    color: str | None = "#ffd60a",
) -> dict:
    """Place a black title card with text effect on a video track."""
    return _require_editor().create_title_card(
        content,
        track_id,
        start_frame,
        duration_frames,
        position=position,
        size=size,
        border_width=border_width,
        color=color,
    )


@mcp.tool()
def paste_attributes_to_clips(
    clip_ids: list[str],
    speed: bool = True,
    position: bool = True,
    gain: bool = True,
    opacity: bool = True,
    fades: bool = True,
) -> dict:
    """Paste attributes clipboard onto many clips."""
    return _require_editor().paste_attributes_to_clips(
        clip_ids,
        speed=speed,
        position=position,
        gain=gain,
        opacity=opacity,
        fades=fades,
    )


@mcp.tool()
def openshot_plan(height: int = 360, include_audio: bool = False) -> dict:
    """OpenShot multi-clip plan (optional audio track listing)."""
    return _require_editor().openshot_plan(
        height=height, include_audio=include_audio,
    )


@mcp.tool()
def quantize_clips(
    clip_ids: list[str],
    grid_frames: int,
    edge: str = "start",
) -> dict:
    """Snap clip starts/ends to a frame grid."""
    return _require_editor().quantize_clips(
        clip_ids, grid_frames, edge=edge,
    )


@mcp.tool()
def snap_clips_to_markers(
    clip_ids: list[str],
    edge: str = "start",
    max_delta_frames: int | None = None,
    prefer: str = "nearest",
) -> dict:
    """Snap clip starts/ends to nearest timeline markers.

    Music cut workflow: markers_from_beats → snap_clips_to_markers.
    prefer: nearest|prev|next.
    """
    return _require_editor().snap_clips_to_markers(
        clip_ids,
        edge=edge,
        max_delta_frames=max_delta_frames,
        prefer=prefer,
    )


@mcp.tool()
def export_audio(
    output_path: str,
    start_frame: int | None = None,
    end_frame: int | None = None,
    sample_rate: int | None = None,
) -> dict:
    """Export mixdown audio only (wav/m4a/mp3)."""
    return _require_editor().export_audio(
        output_path,
        start_frame=start_frame,
        end_frame=end_frame,
        sample_rate=sample_rate,
    )


@mcp.tool()
def import_cutlist(
    text: str | None = None,
    path: str | None = None,
    track_id: str | None = None,
    replace_track: bool = False,
) -> dict:
    """Import CSV cutlist from export_cutlist."""
    return _require_editor().import_cutlist(
        text, path=path, track_id=track_id, replace_track=replace_track,
    )


@mcp.tool()
def set_work_area_from_clip(clip_id: str) -> dict:
    """Set work In/Out to a clip's span."""
    return _require_editor().set_work_area_from_clip(clip_id)


@mcp.tool()
def set_work_area_from_selection(clip_ids: list[str]) -> dict:
    """Set work In/Out to union of clips."""
    return _require_editor().set_work_area_from_selection(clip_ids)


@mcp.tool()
def markers_from_cuts(
    track_id: str,
    label_prefix: str = "Cut",
    color: str = "#ffb703",
    include_start: bool = False,
) -> dict:
    """Add markers at each cut on a track."""
    return _require_editor().markers_from_cuts(
        track_id,
        label_prefix=label_prefix,
        color=color,
        include_start=include_start,
    )


@mcp.tool()
def shift_markers(
    delta_frames: int,
    marker_ids: list[str] | None = None,
) -> dict:
    """Shift markers by delta frames."""
    return _require_editor().shift_markers(delta_frames, marker_ids=marker_ids)


@mcp.tool()
def ripple_delete_range(
    start_frame: int,
    end_frame: int,
    track_id: str | None = None,
    kind: str | None = None,
) -> dict:
    """Ripple-extract range (Premiere-style name)."""
    return _require_editor().ripple_delete_range(
        start_frame, end_frame, track_id=track_id, kind=kind,
    )


@mcp.tool()
def solo_clip(clip_id: str, exclusive: bool = True) -> dict:
    """Mute other clips; leave this one unmuted."""
    return _require_editor().solo_clip(clip_id, exclusive=exclusive)


@mcp.tool()
def unmute_all_clips(track_id: str | None = None) -> dict:
    """Clear clip mutes."""
    return _require_editor().unmute_all_clips(track_id=track_id)


@mcp.tool()
def set_clips_color_cycle(
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
) -> dict:
    """Rotate CLIP_COLORS onto clips."""
    return _require_editor().set_clips_color_cycle(
        clip_ids, track_id=track_id,
    )


@mcp.tool()
def duration_report() -> dict:
    """Per-track duration census."""
    return _require_editor().duration_report()


@mcp.tool()
def prepare_for_export(
    fill_video: bool = True,
    fill_audio: bool = False,
    clear_empty_tracks: bool = True,
) -> dict:
    """Preflight: pack/fill + validate + media status."""
    return _require_editor().prepare_for_export(
        fill_video=fill_video,
        fill_audio=fill_audio,
        clear_empty_tracks=clear_empty_tracks,
    )


@mcp.tool()
def export_still(
    output_path: str,
    frame: int,
    width: int = 1280,
) -> dict:
    """Export one timeline frame as image."""
    return _require_editor().export_still(output_path, frame, width=width)


@mcp.tool()
def clips_sharing_media(media_id: str) -> dict:
    """List clips using a media id."""
    return _require_editor().clips_sharing_media(media_id)


@mcp.tool()
def batch_relink(
    mapping: dict[str, str],
    keep_source_range: bool = True,
) -> dict:
    """Relink many clips: clip_id → media_id map."""
    return _require_editor().batch_relink(
        mapping, keep_source_range=keep_source_range,
    )


@mcp.tool()
def hard_cut_all(track_id: str | None = None) -> dict:
    """Clear transitions and repack hard cuts."""
    return _require_editor().hard_cut_all(track_id=track_id)


@mcp.tool()
def set_marker_color_batch(
    color: str,
    marker_ids: list[str] | None = None,
) -> dict:
    """Batch marker color."""
    return _require_editor().set_marker_color_batch(
        color, marker_ids=marker_ids,
    )


@mcp.tool()
def interchange_formats() -> dict:
    """Catalog of import/export interchange surfaces (OTIO/FCPXML/EDL/…)."""
    return _require_editor().interchange_formats()


@mcp.tool()
def export_fcpxml(path: str | None = None, title: str | None = None) -> dict:
    """Minimal FCPXML 1.9 of base video track."""
    return _require_editor().export_fcpxml(path, title=title)


@mcp.tool()
def import_fcpxml(
    path: str | None = None,
    text: str | None = None,
    clear_track: bool = False,
    import_missing_media: bool = True,
    conform: bool = True,
) -> dict:
    """Import minimal FCPXML 1.9 (pair of export_fcpxml)."""
    return _require_editor().import_fcpxml(
        path,
        text=text,
        clear_track=clear_track,
        import_missing_media=import_missing_media,
        conform=conform,
    )


@mcp.tool()
def export_otio_json(path: str | None = None, title: str | None = None) -> dict:
    """Simplified OTIO-like JSON timeline."""
    return _require_editor().export_otio_json(path, title=title)


@mcp.tool()
def export_edit_manifest(path: str | None = None) -> dict:
    """Compact JSON edit manifest (tracks/clips/effects/markers)."""
    return _require_editor().export_edit_manifest(path)


@mcp.tool()
def import_edit_manifest(
    path: str | None = None,
    text: str | None = None,
    clear: bool = True,
    import_missing_media: bool = True,
    conform: bool = True,
) -> dict:
    """Import edit manifest JSON (pair of export_edit_manifest)."""
    return _require_editor().import_edit_manifest(
        path,
        text=text,
        clear=clear,
        import_missing_media=import_missing_media,
        conform=conform,
    )


@mcp.tool()
def ensure_all_media_proxies(
    height: int = 480,
    force: bool = False,
    kinds: list[str] | None = None,
) -> dict:
    """Build proxies for all video media in the bin."""
    return _require_editor().ensure_all_media_proxies(
        height=height, force=force, kinds=kinds,
    )


@mcp.tool()
def agent_quick_assembly(
    media_paths: list[str],
    track_id: str | None = None,
    rough_cut: bool = True,
    title: str | None = None,
    transition: str | None = "cross_dissolve",
    build_proxies: bool = False,
) -> dict:
    """Import media paths → rough cut → optional title (agent first assembly)."""
    return _require_editor().agent_quick_assembly(
        media_paths,
        track_id=track_id,
        rough_cut=rough_cut,
        title=title,
        transition=transition,
        build_proxies=build_proxies,
    )


@mcp.tool()
def relink_offline_media(
    search_dirs: list[str],
    recursive: bool = True,
    re_probe: bool = True,
) -> dict:
    """Relink offline bin media by basename under search_dirs (copy into bundle)."""
    return _require_editor().relink_offline_media(
        search_dirs, recursive=recursive, re_probe=re_probe,
    )


@mcp.tool()
def export_handoff_package(
    out_dir: str,
    include_manifest: bool = True,
    include_chapters: bool = True,
    include_preflight: bool = True,
    include_otio: bool = False,
    include_media_status: bool = True,
) -> dict:
    """Write agent handoff folder: manifest, chapters, preflight, media status."""
    return _require_editor().export_handoff_package(
        out_dir,
        include_manifest=include_manifest,
        include_chapters=include_chapters,
        include_preflight=include_preflight,
        include_otio=include_otio,
        include_media_status=include_media_status,
    )


@mcp.tool()
def export_review_package(
    out_dir: str,
    include_handoff: bool = True,
    include_storyboard: bool = True,
    include_social: bool = False,
    social_variants: list[str] | None = None,
    watermark: str | None = None,
) -> dict:
    """Handoff + storyboard (+ optional social pack) in one review folder."""
    return _require_editor().export_review_package(
        out_dir,
        include_handoff=include_handoff,
        include_storyboard=include_storyboard,
        include_social=include_social,
        social_variants=social_variants,
        watermark=watermark,
    )


@mcp.tool()
def apply_watermark_to_track(
    track_id: str,
    content: str = "© Opmiere",
    position: str = "bottom",
    size: int = 22,
    alpha: float = 0.55,
    color: str = "white",
) -> dict:
    """Apply text watermark to every clip on a track."""
    return _require_editor().apply_watermark_to_track(
        track_id, content, position=position, size=size, alpha=alpha, color=color,
    )


@mcp.tool()
def collect_to_bundle(
    dest_path: str,
    used_only: bool = True,
    conform: bool = True,
) -> dict:
    """NLE Collect Files: create self-contained .opm with media re-imported."""
    return _require_editor().collect_to_bundle(
        dest_path, used_only=used_only, conform=conform,
    )


@mcp.tool()
def export_frame_sequence(
    out_dir: str,
    start_frame: int | None = None,
    end_frame: int | None = None,
    use_work_area: bool = False,
    pattern: str = "frame_%06d.png",
    max_frames: int | None = None,
    height: int | None = None,
) -> dict:
    """Export timeline/range as image sequence for VFX/grading handoff."""
    return _require_editor().export_frame_sequence(
        out_dir,
        start_frame=start_frame,
        end_frame=end_frame,
        use_work_area=use_work_area,
        pattern=pattern,
        max_frames=max_frames,
        height=height,
    )


@mcp.tool()
def export_storyboard(
    out_dir: str,
    include_markers: bool = True,
    include_clip_mids: bool = True,
    include_contact: bool = True,
    include_chapters: bool = True,
    width: int = 640,
    max_stills: int = 64,
) -> dict:
    """Export review storyboard: stills + contact sheet + chapters."""
    return _require_editor().export_storyboard(
        out_dir,
        include_markers=include_markers,
        include_clip_mids=include_clip_mids,
        include_contact=include_contact,
        include_chapters=include_chapters,
        width=width,
        max_stills=max_stills,
    )


@mcp.tool()
def export_to_size(
    path: str,
    width: int,
    height: int,
    fit: str = "cover",
    normalize_preset: str | None = None,
) -> dict:
    """Export timeline scaled to width×height (cover|contain|stretch)."""
    return _require_editor().export_to_size(
        path, width, height, fit=fit, normalize_preset=normalize_preset,
    )


@mcp.tool()
def export_with_burnins(
    path: str,
    timecode: bool = True,
    safe_area: bool = True,
    watermark: str | None = None,
    timecode_start: str = "00:00:00:00",
    normalize_preset: str | None = None,
) -> dict:
    """Export review master with TC/safe/watermark (timeline unchanged)."""
    return _require_editor().export_with_burnins(
        path,
        timecode=timecode,
        safe_area=safe_area,
        watermark=watermark,
        timecode_start=timecode_start,
        normalize_preset=normalize_preset,
    )


@mcp.tool()
def rename_clips_sequential(
    track_id: str,
    pattern: str = "Shot {n:03d}",
    start: int = 1,
) -> dict:
    """Rename clips on a track in timeline order."""
    return _require_editor().rename_clips_sequential(
        track_id, pattern=pattern, start=start,
    )


@mcp.tool()
def export_social_pack(
    out_dir: str,
    variants: list[str] | None = None,
    normalize_preset: str | None = None,
    name_prefix: str = "export",
) -> dict:
    """Export youtube/reels/square (etc.) social canvases."""
    return _require_editor().export_social_pack(
        out_dir,
        variants=variants,
        normalize_preset=normalize_preset,
        name_prefix=name_prefix,
    )


@mcp.tool()
def reframe_clip(
    clip_id: str,
    aspect: str = "9:16",
    anchor: str = "center",
) -> dict:
    """Crop clip to aspect ratio (9:16, 1:1, …) for vertical/social reframes."""
    return _require_editor().reframe_clip(clip_id, aspect, anchor=anchor)


@mcp.tool()
def set_clip_timecode(
    clip_id: str,
    enabled: bool = True,
    position: str = "bottom",
    size: int = 28,
    start: str = "00:00:00:00",
) -> dict:
    """Burn running timecode overlay on a clip."""
    return _require_editor().set_clip_timecode(
        clip_id, enabled=enabled, position=position, size=size, start=start,
    )


@mcp.tool()
def markers_from_clips(
    track_id: str | None = None,
    at: str = "start",
    prefix: str = "",
    clear_existing: bool = False,
    color: str = "#7c9cff",
) -> dict:
    """Create markers at each clip start/mid/end (chapter scaffold)."""
    return _require_editor().markers_from_clips(
        track_id, at=at, prefix=prefix, clear_existing=clear_existing, color=color,
    )


@mcp.tool()
def set_clip_watermark(
    clip_id: str,
    content: str = "© Opmiere",
    position: str = "bottom",
    size: int = 22,
    alpha: float = 0.55,
    color: str = "white",
    enabled: bool = True,
) -> dict:
    """Set text watermark on a clip (replaces existing watermark)."""
    return _require_editor().set_clip_watermark(
        clip_id,
        content,
        position=position,
        size=size,
        alpha=alpha,
        color=color,
        enabled=enabled,
    )


@mcp.tool()
def list_cuts(track_id: str | None = None, kind: str | None = "video") -> dict:
    """List hard-cut edit points for razor/transition planning."""
    return _require_editor().list_cuts(track_id, kind=kind)


@mcp.tool()
def set_clip_safe_area(
    clip_id: str,
    enabled: bool = True,
    action: float = 0.90,
    title: float = 0.80,
    thickness: int = 2,
) -> dict:
    """Burn action/title safe rectangles on a clip (review overlay)."""
    return _require_editor().set_clip_safe_area(
        clip_id, enabled=enabled, action=action, title=title, thickness=thickness,
    )


@mcp.tool()
def apply_safe_area_to_track(
    track_id: str,
    action: float = 0.90,
    title: float = 0.80,
    thickness: int = 2,
) -> dict:
    """Apply safe_area overlay to every clip on a track."""
    return _require_editor().apply_safe_area_to_track(
        track_id, action=action, title=title, thickness=thickness,
    )


@mcp.tool()
def export_cuts_report(
    path: str | None = None,
    track_id: str | None = None,
    kind: str | None = "video",
    format: str = "json",
) -> dict:
    """Export cut list as JSON or CSV file (or body when path is None)."""
    return _require_editor().export_cuts_report(
        path, track_id=track_id, kind=kind, format=format,
    )


@mcp.tool()
def find_clips(
    name_contains: str | None = None,
    media_id: str | None = None,
    color: str | None = None,
    track_id: str | None = None,
    kind: str | None = None,
    has_effect: str | None = None,
    muted: bool | None = None,
) -> dict:
    """Search clips by name/media/color/effect/mute."""
    return _require_editor().find_clips(
        name_contains=name_contains,
        media_id=media_id,
        color=color,
        track_id=track_id,
        kind=kind,
        has_effect=has_effect,
        muted=muted,
    )


@mcp.tool()
def isolate_clips(
    clip_ids: list[str],
    track_id: str | None = None,
    follow_links: bool = True,
) -> dict:
    """Unmute selected clips; mute every other clip (solo-by-mute)."""
    return _require_editor().isolate_clips(
        clip_ids, track_id=track_id, follow_links=follow_links,
    )


@mcp.tool()
def apply_crossfades_on_track(
    track_id: str,
    duration_frames: int = 12,
    transition_type: str = "cross_dissolve",
    max_count: int | None = None,
) -> dict:
    """Add crossfades on every hard cut (video xfade / audio acrossfade)."""
    return _require_editor().apply_crossfades_on_track(
        track_id,
        duration_frames=duration_frames,
        transition_type=transition_type,
        max_count=max_count,
    )


@mcp.tool()
def markers_from_hard_cuts(
    track_id: str | None = None,
    prefix: str = "Cut ",
    clear_existing: bool = False,
    color: str = "#ff9f43",
) -> dict:
    """Place markers at each hard cut."""
    return _require_editor().markers_from_hard_cuts(
        track_id, prefix=prefix, clear_existing=clear_existing, color=color,
    )


@mcp.tool()
def set_project_resolution(width: int, height: int) -> dict:
    """Change timeline canvas size (does not re-encode media)."""
    return _require_editor().set_project_resolution(width, height)


@mcp.tool()
def markers_from_blackdetect(
    media_id: str | None = None,
    path: str | None = None,
    clip_id: str | None = None,
    pic_th: float = 0.98,
    pix_th: float = 0.10,
    min_duration: float = 0.15,
    prefix: str = "Black ",
    clear_existing: bool = False,
    color: str = "#111111",
    max_markers: int = 64,
) -> dict:
    """ffmpeg blackdetect → markers at black segment starts."""
    return _require_editor().markers_from_blackdetect(
        media_id,
        path=path,
        clip_id=clip_id,
        pic_th=pic_th,
        pix_th=pix_th,
        min_duration=min_duration,
        prefix=prefix,
        clear_existing=clear_existing,
        color=color,
        max_markers=max_markers,
    )


@mcp.tool()
def markers_from_silencedetect(
    media_id: str | None = None,
    path: str | None = None,
    clip_id: str | None = None,
    noise_db: float = -30.0,
    min_duration: float = 0.25,
    mark: str = "start",
    prefix: str = "Silence ",
    clear_existing: bool = False,
    color: str = "#5c7cfa",
    max_markers: int = 80,
) -> dict:
    """ffmpeg silencedetect → markers at silence start/end."""
    return _require_editor().markers_from_silencedetect(
        media_id,
        path=path,
        clip_id=clip_id,
        noise_db=noise_db,
        min_duration=min_duration,
        mark=mark,
        prefix=prefix,
        clear_existing=clear_existing,
        color=color,
        max_markers=max_markers,
    )


@mcp.tool()
def split_at_silences(
    clip_id: str,
    noise_db: float = -30.0,
    min_duration: float = 0.25,
    max_splits: int = 40,
    mark: str = "start",
) -> dict:
    """Razor a clip at silence starts or ends."""
    return _require_editor().split_at_silences(
        clip_id,
        noise_db=noise_db,
        min_duration=min_duration,
        max_splits=max_splits,
        mark=mark,
    )


@mcp.tool()
def tighten_silences(
    clip_id: str,
    noise_db: float = -30.0,
    min_duration: float = 0.35,
    pad_frames: int = 4,
    max_ranges: int = 40,
) -> dict:
    """Ripple-remove interior silence ranges (dialogue tighten)."""
    return _require_editor().tighten_silences(
        clip_id,
        noise_db=noise_db,
        min_duration=min_duration,
        pad_frames=pad_frames,
        max_ranges=max_ranges,
    )


@mcp.tool()
def set_project_fps(fps: float) -> dict:
    """Change project timebase fps (frame counts kept)."""
    return _require_editor().set_project_fps(fps)


@mcp.tool()
def apply_gain_to_track(track_id: str, db: float) -> dict:
    """Set gain dB on every clip of a track."""
    return _require_editor().apply_gain_to_track(track_id, db)


@mcp.tool()
def apply_noise_reduction_to_track(track_id: str, amount: float = 12.0) -> dict:
    """Apply noise_reduction effect to every clip on a track."""
    return _require_editor().apply_noise_reduction_to_track(track_id, amount)


@mcp.tool()
def list_silence_ranges(
    media_id: str | None = None,
    path: str | None = None,
    clip_id: str | None = None,
    noise_db: float = -30.0,
    min_duration: float = 0.25,
    pad_frames: int = 0,
    max_ranges: int = 80,
) -> dict:
    """Read-only silence range report (plan before tighten_silences)."""
    return _require_editor().list_silence_ranges(
        media_id,
        path=path,
        clip_id=clip_id,
        noise_db=noise_db,
        min_duration=min_duration,
        pad_frames=pad_frames,
        max_ranges=max_ranges,
    )


@mcp.tool()
def export_project_snapshot(
    path: str,
    include_media_status: bool = True,
    include_preflight: bool = True,
    include_cuts: bool = True,
) -> dict:
    """Write recovery/agent project snapshot JSON (no media files)."""
    return _require_editor().export_project_snapshot(
        path,
        include_media_status=include_media_status,
        include_preflight=include_preflight,
        include_cuts=include_cuts,
    )


@mcp.tool()
def export_presets_pack(
    out_dir: str,
    presets: list[str] | None = None,
    name_prefix: str = "export",
    prepare: bool | None = None,
) -> dict:
    """Export multiple named presets (draft/streaming/…) into a folder."""
    return _require_editor().export_presets_pack(
        out_dir, presets=presets, name_prefix=name_prefix, prepare=prepare,
    )


@mcp.tool()
def match_clip_duration(
    clip_id: str,
    target_clip_id: str | None = None,
    target_frames: int | None = None,
    clamp: bool = True,
) -> dict:
    """Rate-stretch a clip to match another clip's duration or frame count."""
    return _require_editor().match_clip_duration(
        clip_id,
        target_clip_id=target_clip_id,
        target_frames=target_frames,
        clamp=clamp,
    )


@mcp.tool()
def set_pip_corner(
    clip_id: str,
    corner: str = "bottom_right",
    scale: float = 0.28,
) -> dict:
    """Set picture-in-picture corner on an overlay clip."""
    return _require_editor().set_pip_corner(clip_id, corner, scale=scale)


@mcp.tool()
def place_pip(
    media_id: str,
    corner: str = "bottom_right",
    scale: float = 0.28,
    start: int | None = None,
    duration_frames: int | None = None,
    track_id: str | None = None,
    name: str | None = None,
) -> dict:
    """Place media as PiP on an overlay video track."""
    return _require_editor().place_pip(
        media_id,
        corner=corner,
        scale=scale,
        start=start,
        duration_frames=duration_frames,
        track_id=track_id,
        name=name,
    )


@mcp.tool()
def add_lower_third(
    content: str,
    start_frame: int | None = None,
    duration_frames: int = 90,
    track_id: str | None = None,
    size: int = 42,
    color: str = "#ffd60a",
) -> dict:
    """Add lower-third title (black slug + text) on overlay track."""
    return _require_editor().add_lower_third(
        content,
        start_frame=start_frame,
        duration_frames=duration_frames,
        track_id=track_id,
        size=size,
        color=color,
    )


@mcp.tool()
def add_end_card(
    content: str = "Thanks for watching",
    duration_frames: int = 90,
    track_id: str | None = None,
    size: int = 56,
    fade_in_frames: int = 12,
) -> dict:
    """Append a title end-card after the current sequence end."""
    return _require_editor().add_end_card(
        content,
        duration_frames=duration_frames,
        track_id=track_id,
        size=size,
        fade_in_frames=fade_in_frames,
    )


@mcp.tool()
def place_split_screen(
    media_left_id: str,
    media_right_id: str,
    start: int = 0,
    duration_frames: int | None = None,
    orientation: str = "lr",
) -> dict:
    """Place two media side-by-side (lr) or top/bottom (tb) split-screen."""
    return _require_editor().place_split_screen(
        media_left_id,
        media_right_id,
        start=start,
        duration_frames=duration_frames,
        orientation=orientation,
    )


@mcp.tool()
def add_intro_card(
    content: str = "Title",
    duration_frames: int = 90,
    track_id: str | None = None,
    size: int = 56,
    fade_out_frames: int = 12,
    ripple_all_tracks: bool = True,
) -> dict:
    """Prepend a title intro card at frame 0 (ripples later clips by default)."""
    return _require_editor().add_intro_card(
        content,
        duration_frames=duration_frames,
        track_id=track_id,
        size=size,
        fade_out_frames=fade_out_frames,
        ripple_all_tracks=ripple_all_tracks,
    )


@mcp.tool()
def place_quad_screen(
    media_ids: list[str],
    start: int = 0,
    duration_frames: int | None = None,
) -> dict:
    """Place four media_ids in a 2×2 grid (TL/TR/BL/BR)."""
    return _require_editor().place_quad_screen(
        media_ids,
        start=start,
        duration_frames=duration_frames,
    )


@mcp.tool()
def replace_media_everywhere(
    old_media_id: str,
    new_media_id: str,
    keep_source_range: bool = True,
    track_id: str | None = None,
) -> dict:
    """Retarget every clip using old_media_id → new_media_id."""
    return _require_editor().replace_media_everywhere(
        old_media_id,
        new_media_id,
        keep_source_range=keep_source_range,
        track_id=track_id,
    )


@mcp.tool()
def import_image_sequence(
    path: str,
    fps: float | None = None,
    glob: str = "*",
    start_number: int | None = None,
    max_frames: int | None = None,
    place_track_id: str | None = None,
    start: int = 0,
    build_proxy: bool = False,
) -> dict:
    """Encode a still sequence (dir / pattern) to video and import."""
    return _require_editor().import_image_sequence(
        path,
        fps=fps,
        glob=glob,
        start_number=start_number,
        max_frames=max_frames,
        place_track_id=place_track_id,
        start=start,
        build_proxy=build_proxy,
    )


@mcp.tool()
def import_folder(
    folder: str,
    recursive: bool = False,
    kinds: list[str] | None = None,
    place: bool = False,
    track_id: str | None = None,
    rough_cut: bool = False,
    transition: str | None = "cross_dissolve",
    max_files: int = 200,
    conform: bool = True,
) -> dict:
    """Import all media files from a folder (optional place / rough_cut)."""
    return _require_editor().import_folder(
        folder,
        recursive=recursive,
        kinds=kinds,
        place=place,
        track_id=track_id,
        rough_cut=rough_cut,
        transition=transition,
        max_files=max_files,
        conform=conform,
    )


@mcp.tool()
def detach_audio_all(
    track_id: str | None = None,
    audio_track_id: str | None = None,
    audio_start_offset_frames: int = 0,
    link: bool = True,
    only_with_audio: bool = True,
) -> dict:
    """Detach audio for every video clip on a track (or all video tracks)."""
    return _require_editor().detach_audio_all(
        track_id,
        audio_track_id=audio_track_id,
        audio_start_offset_frames=audio_start_offset_frames,
        link=link,
        only_with_audio=only_with_audio,
    )


@mcp.tool()
def set_j_l_offset(
    video_clip_id: str,
    offset_frames: int,
    relative: bool = False,
) -> dict:
    """Shift linked audio peer(s): negative=J-cut lead, positive=L-cut lag."""
    return _require_editor().set_j_l_offset(
        video_clip_id, offset_frames, relative=relative,
    )


@mcp.tool()
def import_otio_json(
    path: str | None = None,
    text: str | None = None,
    clear_tracks: bool = False,
    import_missing_media: bool = True,
    conform: bool = True,
) -> dict:
    """Import simplified OTIO-like JSON (pair of export_otio_json).

    Matches media by path/basename; imports missing files when on disk.
    """
    return _require_editor().import_otio_json(
        path,
        text=text,
        clear_tracks=clear_tracks,
        import_missing_media=import_missing_media,
        conform=conform,
    )


@mcp.tool()
def agent_preflight() -> dict:
    """Read-only gate: media + validate + proxy + duration + next_steps.

    Call before a batch of edits and before agent_finish_session.
    ready=true means structure ok; still ensure_preview_proxy for scrub.
    """
    return _require_editor().agent_preflight()


@mcp.tool()
def agent_finish_session(
    export_path: str,
    prepare: bool = True,
    ensure_proxy: bool = True,
    proxy_height: int = 360,
    proxy_fps: float = 12.0,
    run_review: bool = True,
    normalize_preset: str | None = "streaming",
    delivery_preset: str = "streaming",
) -> dict:
    """Canonical agent end-of-cut pipeline.

    Order: agent_preflight → ensure_preview_proxy → prepare_for_export →
    finish_delivery (review + export + delivery_check). Prefer this over
    calling export alone so gates are not skipped.
    """
    return _require_editor().agent_finish_session(
        export_path,
        prepare=prepare,
        ensure_proxy=ensure_proxy,
        proxy_height=proxy_height,
        proxy_fps=proxy_fps,
        run_review=run_review,
        normalize_preset=normalize_preset,
        delivery_preset=delivery_preset,
    )


@mcp.tool()
def clear_clip_effects(
    clip_id: str,
    types: list[str] | None = None,
) -> dict:
    """Remove all effects, or only those whose type is in types."""
    return _require_editor().clear_clip_effects(clip_id, types=types)


@mcp.tool()
def list_clip_effects(clip_id: str) -> dict:
    """List effect dicts on a clip."""
    return _require_editor().list_clip_effects(clip_id)


@mcp.tool()
def list_export_presets() -> dict:
    """Named export recipes: draft/streaming/youtube/broadcast/review."""
    return _require_editor().list_export_presets()


@mcp.tool()
def export_with_preset(
    output_path: str,
    preset: str = "streaming",
    prepare: bool | None = None,
) -> dict:
    """Export using a named preset (normalize + optional delivery_check)."""
    return _require_editor().export_with_preset(
        output_path, preset=preset, prepare=prepare,
    )


@mcp.tool()
def move_to_track(
    clip_id: str,
    track_id: str,
    start: int | None = None,
) -> dict:
    """Reparent clip onto another track of the same kind."""
    return _require_editor().move_to_track(clip_id, track_id, start=start)


@mcp.tool()
def align_clips(
    clip_ids: list[str],
    to_frame: int = 0,
    mode: str = "relative",
) -> dict:
    """Align clip starts: relative (group shift) or start (stack at frame)."""
    return _require_editor().align_clips(
        clip_ids, to_frame=to_frame, mode=mode,
    )


@mcp.tool()
def copy_effects(clip_id: str) -> dict:
    """Copy clip effects into session effects clipboard."""
    return _require_editor().copy_effects(clip_id)


@mcp.tool()
def paste_effects(clip_id: str, replace: bool = True) -> dict:
    """Paste effects clipboard onto a clip (replace or append)."""
    return _require_editor().paste_effects(clip_id, replace=replace)


@mcp.tool()
def stretch_to(
    clip_id: str,
    target_duration_frames: int,
    clamp: bool = True,
) -> dict:
    """Rate-stretch clip to target timeline duration (speed 0.25–4)."""
    return _require_editor().stretch_to(
        clip_id, target_duration_frames, clamp=clamp,
    )


@mcp.tool()
def clips_on_track(track_id: str, ordered: bool = True) -> dict:
    """List clips on a track."""
    return _require_editor().clips_on_track(track_id, ordered=ordered)


@mcp.tool()
def marker_near(
    frame: int,
    direction: str = "next",
    wrap: bool = False,
) -> dict:
    """Find next/prev/nearest marker relative to a frame."""
    return _require_editor().marker_near(
        frame, direction=direction, wrap=wrap,
    )


@mcp.tool()
def apply_effect_to_clips(clip_ids: list[str], effect: dict) -> dict:
    """Append one effect to many clips (one undo)."""
    return _require_editor().apply_effect_to_clips(clip_ids, effect)


@mcp.tool()
def set_clip_crop(
    clip_id: str,
    width: int,
    height: int,
    x: int | str | None = None,
    y: int | str | None = None,
) -> dict:
    """Replace crop effect (pixel width/height; optional x/y)."""
    return _require_editor().set_clip_crop(
        clip_id, width, height, x=x, y=y,
    )


@mcp.tool()
def find_gaps(
    track_id: str | None = None,
    from_frame: int = 0,
    min_gap_frames: int = 1,
) -> dict:
    """Report holes between clips on one or all tracks."""
    return _require_editor().find_gaps(
        track_id, from_frame=from_frame, min_gap_frames=min_gap_frames,
    )


@mcp.tool()
def close_all_gaps(from_frame: int = 0) -> dict:
    """Pack every unlocked track leftward from from_frame."""
    return _require_editor().close_all_gaps(from_frame=from_frame)


@mcp.tool()
def remove_empty_tracks(keep_one_per_kind: bool = True) -> dict:
    """Delete empty tracks (optionally keep one empty video/audio)."""
    return _require_editor().remove_empty_tracks(
        keep_one_per_kind=keep_one_per_kind,
    )


@mcp.tool()
def list_tracks() -> dict:
    """Summarize tracks (id, kind, clip_count, M/S/L)."""
    return _require_editor().list_tracks()


@mcp.tool()
def set_clip_rotate(clip_id: str, degrees: float) -> dict:
    """Set rotate degrees (0 clears). Replaces existing rotate effect."""
    return _require_editor().set_clip_rotate(clip_id, degrees)


@mcp.tool()
def set_clip_flip(
    clip_id: str,
    horizontal: bool | None = None,
    vertical: bool | None = None,
    toggle_h: bool = False,
    toggle_v: bool = False,
) -> dict:
    """Set or toggle hflip/vflip (mirror) on a clip."""
    return _require_editor().set_clip_flip(
        clip_id,
        horizontal=horizontal,
        vertical=vertical,
        toggle_h=toggle_h,
        toggle_v=toggle_v,
    )


@mcp.tool()
def export_clip_media(
    out_dir: str,
    clip_ids: list[str] | None = None,
    track_id: str | None = None,
    include_audio: bool = True,
    container: str = "mp4",
) -> dict:
    """Export each clip's source range as standalone media (NLE subclip files)."""
    return _require_editor().export_clip_media(
        out_dir,
        clip_ids,
        track_id=track_id,
        include_audio=include_audio,
        container=container,
    )


@mcp.tool()
def bake_clip(
    clip_id: str,
    replace: bool = True,
    clear_effects: bool = True,
    include_audio: bool = True,
) -> dict:
    """Render-and-replace: bake clip effects into new media."""
    return _require_editor().bake_clip(
        clip_id,
        replace=replace,
        clear_effects=clear_effects,
        include_audio=include_audio,
    )


@mcp.tool()
def add_grade_layer(
    effects: list[dict] | None = None,
    start: int = 0,
    end: int | None = None,
    track_id: str | None = None,
    opacity: float = 1.0,
    name: str = "Grade",
) -> dict:
    """Add overlay video track with black slug for global grade/FX."""
    return _require_editor().add_grade_layer(
        effects,
        start=start,
        end=end,
        track_id=track_id,
        opacity=opacity,
        name=name,
    )


@mcp.tool()
def project_health_report() -> dict:
    """Read-only health: preflight + gaps + unused + path-C + stats."""
    return _require_editor().project_health_report()


@mcp.tool()
def reset_clip_transform(
    clip_id: str,
    position: bool = True,
    crop: bool = True,
    rotate: bool = True,
    opacity: bool = True,
) -> dict:
    """Clear PiP position / crop / rotate / opacity (not grade effects)."""
    return _require_editor().reset_clip_transform(
        clip_id,
        position=position,
        crop=crop,
        rotate=rotate,
        opacity=opacity,
    )


@mcp.tool()
def swap_clips(clip_a: str, clip_b: str) -> dict:
    """Swap two clips' timeline start times."""
    return _require_editor().swap_clips(clip_a, clip_b)


@mcp.tool()
def move_track(
    track_id: str,
    index: int | None = None,
    delta: int | None = None,
) -> dict:
    """Reorder track (index or delta). Later video tracks = higher overlay."""
    return _require_editor().move_track(track_id, index=index, delta=delta)


@mcp.tool()
def set_track_name(track_id: str, name: str | None = None) -> dict:
    """Set optional track display name."""
    return _require_editor().set_track_name(track_id, name)


@mcp.tool()
def clips_at(
    timeline_frame: int,
    track_id: str | None = None,
    kind: str | None = None,
) -> dict:
    """Hit-test clips covering a timeline frame."""
    return _require_editor().clips_at(
        timeline_frame, track_id=track_id, kind=kind,
    )


@mcp.tool()
def match_frame(
    timeline_frame: int | None = None,
    clip_id: str | None = None,
) -> dict:
    """Map timeline position to source media frame (NLE Match Frame)."""
    return _require_editor().match_frame(
        timeline_frame=timeline_frame, clip_id=clip_id,
    )


@mcp.tool()
def set_clip_fades(
    clip_id: str,
    fade_in_frames: int = 0,
    fade_out_frames: int = 0,
) -> dict:
    """Set fade-in / fade-out (replaces existing fade effects)."""
    return _require_editor().set_clip_fades(
        clip_id,
        fade_in_frames=fade_in_frames,
        fade_out_frames=fade_out_frames,
    )


@mcp.tool()
def get_clip_fades(clip_id: str) -> dict:
    """Read fade-in / fade-out frame counts."""
    return _require_editor().get_clip_fades(clip_id)


@mcp.tool()
def set_clip_opacity(clip_id: str, amount: float) -> dict:
    """Set clip opacity 0..1 (replaces existing opacity effect)."""
    return _require_editor().set_clip_opacity(clip_id, amount)


@mcp.tool()
def get_clip_opacity(clip_id: str) -> dict:
    """Read clip opacity amount (1.0 = fully opaque)."""
    return {
        "clip_id": clip_id,
        "opacity": _require_editor().get_clip_opacity(clip_id),
    }


@mcp.tool()
def history_status() -> dict:
    """Undo/redo depth, dirty, clipboard, work In/Out."""
    return _require_editor().history_status()


@mcp.tool()
def make_subclip(
    clip_id: str,
    timeline_start: int | None = None,
    timeline_end: int | None = None,
    use_work_area: bool = False,
    place: str = "after",
    name: str | None = None,
) -> dict:
    """Create a subclip from a timeline range or work In/Out."""
    return _require_editor().make_subclip(
        clip_id,
        timeline_start=timeline_start,
        timeline_end=timeline_end,
        use_work_area=use_work_area,
        place=place,
        name=name,
    )


@mcp.tool()
def update_marker(
    marker_id: str,
    label: str | None = None,
    color: str | None = None,
    frame: int | None = None,
    time_seconds: float | None = None,
) -> dict:
    """Update marker label / color / frame."""
    return _require_editor().update_marker(
        marker_id,
        label=label,
        color=color,
        frame=frame,
        time_seconds=time_seconds,
    )


@mcp.tool()
def relink_clip(
    clip_id: str,
    media_id: str,
    keep_source_range: bool = True,
) -> dict:
    """Point clip at different project media (relink / replace source)."""
    return _require_editor().relink_clip(
        clip_id, media_id, keep_source_range=keep_source_range,
    )


@mcp.tool()
def list_style_assets() -> dict:
    """List LUTs/audio beds found under assets/ or OPMIERE_STYLE_ASSETS."""
    return _require_editor().list_style_assets()


@mcp.tool()
def split_clip(
    clip_id: str,
    at_frame: int,
    follow_links: bool = False,
) -> dict:
    """Split at timeline frame. follow_links also splits linked peers."""
    r = _require_editor().split_clip(
        clip_id, at_frame, follow_links=follow_links,
    )
    if isinstance(r, tuple):
        first, second = r
        return {"first": first.to_dict(), "second": second.to_dict()}
    return r


@mcp.tool()
def j_cut(video_clip_id: str, lead_frames: int) -> dict:
    """J-cut: linked audio leads picture by lead_frames."""
    return _require_editor().j_cut(video_clip_id, lead_frames)


@mcp.tool()
def l_cut(video_clip_id: str, lag_frames: int) -> dict:
    """L-cut: linked audio lags picture by lag_frames."""
    return _require_editor().l_cut(video_clip_id, lag_frames)


@mcp.tool()
def offset_linked(
    clip_id: str,
    delta_frames: int,
    kinds: list[str] | None = None,
) -> dict:
    """Nudge link-group peers by delta (default all peers except anchor)."""
    return _require_editor().offset_linked(
        clip_id, delta_frames, kinds=kinds,
    )


@mcp.tool()
def duplicate_track(
    track_id: str,
    copy_clips: bool = True,
    name: str | None = None,
) -> dict:
    """Duplicate a track (optionally with clip copies)."""
    return _require_editor().duplicate_track(
        track_id, copy_clips=copy_clips, name=name,
    )


@mcp.tool()
def list_unused_media() -> dict:
    """Media not referenced by any clip."""
    return _require_editor().list_unused_media()


@mcp.tool()
def purge_unused_media(delete_files: bool = False) -> dict:
    """Remove unused media from project; optionally delete files."""
    return _require_editor().purge_unused_media(delete_files=delete_files)


@mcp.tool()
def project_stats() -> dict:
    """Project census: duration, counts, dirty, undo depth."""
    return _require_editor().project_stats()


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
    link: bool = True,
) -> dict:
    """Split picture/sound: copy clip audio to an audio track for J/L timing.

    audio_start_offset_frames: negative = audio leads (J-cut), positive = lags.
    While any audio-track clips exist, embedded video audio is not mixed.
    link=True assigns shared link_group for nudge/delete.
    """
    return _require_editor().detach_audio(
        clip_id,
        audio_track_id,
        audio_start_offset_frames=audio_start_offset_frames,
        link=link,
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
def export_gif(
    output_path: str,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    fps: float = 12.0,
    width: int = 480,
    max_duration_seconds: float = 15.0,
) -> dict:
    """Export a timeline range as animated GIF (palettegen)."""
    return _require_editor().export_gif(
        output_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        fps=fps,
        width=width,
        max_duration_seconds=max_duration_seconds,
    )


@mcp.tool()
def export_work_area_gif(
    output_path: str,
    fps: float = 12.0,
    width: int = 480,
    max_duration_seconds: float = 15.0,
) -> dict:
    """Export the in/out work area as animated GIF."""
    return _require_editor().export_work_area_gif(
        output_path,
        fps=fps,
        width=width,
        max_duration_seconds=max_duration_seconds,
    )


@mcp.tool()
def add_solid(
    color: str = "#000000",
    duration_frames: int = 30,
    start: int | None = None,
    track_id: str | None = None,
    name: str | None = None,
    append: bool = True,
) -> dict:
    """Place a solid color matte on a video track."""
    return _require_editor().add_solid(
        color,
        duration_frames=duration_frames,
        start=start,
        track_id=track_id,
        name=name,
        append=append,
    )


@mcp.tool()
def apply_ken_burns(
    clip_id: str,
    zoom_start: float = 1.0,
    zoom_end: float = 1.15,
    x_start: float = 0.5,
    y_start: float = 0.5,
    x_end: float = 0.5,
    y_end: float = 0.5,
    replace: bool = True,
) -> dict:
    """Apply Ken Burns zoom/pan effect to a clip."""
    return _require_editor().apply_ken_burns(
        clip_id,
        zoom_start=zoom_start,
        zoom_end=zoom_end,
        x_start=x_start,
        y_start=y_start,
        x_end=x_end,
        y_end=y_end,
        replace=replace,
    )


@mcp.tool()
def apply_vignette(
    clip_id: str,
    strength: float = 0.45,
    replace: bool = True,
) -> dict:
    """Apply vignette effect to a clip."""
    return _require_editor().apply_vignette(
        clip_id, strength=strength, replace=replace,
    )


@mcp.tool()
def apply_film_grain(
    clip_id: str,
    amount: float = 12.0,
    replace: bool = True,
) -> dict:
    """Apply film grain to a clip (amount in (0, 100])."""
    return _require_editor().apply_film_grain(
        clip_id, amount=amount, replace=replace,
    )


@mcp.tool()
def apply_blur(
    clip_id: str,
    amount: float = 5.0,
    replace: bool = True,
) -> dict:
    """Apply blur to a clip."""
    return _require_editor().apply_blur(
        clip_id, amount=amount, replace=replace,
    )


@mcp.tool()
def apply_sharpen(
    clip_id: str,
    amount: float = 1.0,
    replace: bool = True,
) -> dict:
    """Apply sharpen to a clip (amount in (0, 5])."""
    return _require_editor().apply_sharpen(
        clip_id, amount=amount, replace=replace,
    )


@mcp.tool()
def apply_glow(
    clip_id: str,
    amount: float = 8.0,
    intensity: float = 0.4,
    replace: bool = True,
) -> dict:
    """Apply glow to a clip."""
    return _require_editor().apply_glow(
        clip_id, amount=amount, intensity=intensity, replace=replace,
    )


@mcp.tool()
def apply_chroma_key(
    clip_id: str,
    color: str = "green",
    similarity: float = 0.15,
    blend: float = 0.05,
    replace: bool = True,
) -> dict:
    """Apply chroma key (green/blue screen) for overlay compositing."""
    return _require_editor().apply_chroma_key(
        clip_id,
        color=color,
        similarity=similarity,
        blend=blend,
        replace=replace,
    )


@mcp.tool()
def apply_luma_key(
    clip_id: str,
    threshold: float = 0.1,
    tolerance: float = 0.1,
    replace: bool = True,
) -> dict:
    """Apply luma key (brightness matte) for overlay compositing."""
    return _require_editor().apply_luma_key(
        clip_id,
        threshold=threshold,
        tolerance=tolerance,
        replace=replace,
    )


@mcp.tool()
def apply_white_balance(
    clip_id: str,
    temperature: float = 6500.0,
    mix: float = 1.0,
    replace: bool = True,
) -> dict:
    """Apply white balance (Kelvin temperature) to a clip."""
    return _require_editor().apply_white_balance(
        clip_id,
        temperature=temperature,
        mix=mix,
        replace=replace,
    )


@mcp.tool()
def export_work_area_webm(
    output_path: str,
    crf: int = 32,
    width: int | None = None,
) -> dict:
    """Export the in/out work area as WebM (VP9+Opus)."""
    return _require_editor().export_work_area_webm(
        output_path, crf=crf, width=width,
    )


@mcp.tool()
def apply_shape_mask(
    clip_id: str,
    shape: str = "circle",
    cx: float = 0.5,
    cy: float = 0.5,
    size: float = 0.5,
    feather: float = 0.05,
    width: float = 0.5,
    height: float = 0.5,
    invert: bool = False,
    replace: bool = True,
) -> dict:
    """Apply circular or rectangular shape mask to a clip."""
    return _require_editor().apply_shape_mask(
        clip_id,
        shape=shape,
        cx=cx,
        cy=cy,
        size=size,
        feather=feather,
        width=width,
        height=height,
        invert=invert,
        replace=replace,
    )


@mcp.tool()
def apply_curves(
    clip_id: str,
    preset: str = "increase_contrast",
    replace: bool = True,
) -> dict:
    """Apply curves color grade preset (e.g. vintage, increase_contrast)."""
    return _require_editor().apply_curves(
        clip_id, preset=preset, replace=replace,
    )


@mcp.tool()
def export_clip_webm(
    clip_id: str,
    output_path: str,
    crf: int = 32,
    width: int | None = None,
) -> dict:
    """Export a clip's timeline span as WebM."""
    return _require_editor().export_clip_webm(
        clip_id, output_path, crf=crf, width=width,
    )


@mcp.tool()
def apply_compression(
    clip_id: str,
    ratio: float = 4.0,
    threshold_db: float = -18.0,
    attack_ms: float = 20.0,
    release_ms: float = 250.0,
    makeup_db: float = 0.0,
    replace: bool = True,
) -> dict:
    """Apply audio compression to a clip."""
    return _require_editor().apply_compression(
        clip_id,
        ratio=ratio,
        threshold_db=threshold_db,
        attack_ms=attack_ms,
        release_ms=release_ms,
        makeup_db=makeup_db,
        replace=replace,
    )


@mcp.tool()
def apply_audio_eq(
    clip_id: str,
    frequency_hz: float = 1000.0,
    gain_db: float = 0.0,
    q: float = 1.0,
    replace: bool = False,
) -> dict:
    """Apply a parametric EQ band to a clip (append by default)."""
    return _require_editor().apply_audio_eq(
        clip_id,
        frequency_hz=frequency_hz,
        gain_db=gain_db,
        q=q,
        replace=replace,
    )


@mcp.tool()
def export_clip_audio(
    clip_id: str,
    output_path: str,
    sample_rate: int | None = None,
) -> dict:
    """Export mixdown audio for a clip span (wav/m4a/mp3 by suffix)."""
    return _require_editor().export_clip_audio(
        clip_id, output_path, sample_rate=sample_rate,
    )


@mcp.tool()
def apply_noise_reduction(
    clip_id: str,
    amount: float = 12.0,
    replace: bool = True,
) -> dict:
    """Apply noise reduction to a single clip."""
    return _require_editor().apply_noise_reduction(
        clip_id, amount=amount, replace=replace,
    )


@mcp.tool()
def export_clip_mp4(
    clip_id: str,
    output_path: str,
    normalize_preset: str | None = None,
) -> dict:
    """Export a clip's timeline span as MP4."""
    return _require_editor().export_clip_mp4(
        clip_id, output_path, normalize_preset=normalize_preset,
    )


@mcp.tool()
def add_countdown(
    seconds: int = 3,
    frames_per_digit: int | None = None,
    track_id: str | None = None,
    size: int = 96,
    ripple_all_tracks: bool = True,
) -> dict:
    """Prepend a 3-2-1 title countdown (ripples content by default)."""
    return _require_editor().add_countdown(
        seconds=seconds,
        frames_per_digit=frames_per_digit,
        track_id=track_id,
        size=size,
        ripple_all_tracks=ripple_all_tracks,
    )


@mcp.tool()
def set_speed_ripple(clip_id: str, speed: float) -> dict:
    """Set clip speed and ripple later clips on the same track."""
    return _require_editor().set_speed_ripple(clip_id, speed)


@mcp.tool()
def export_clip_still(
    clip_id: str,
    output_path: str,
    at: str = "mid",
    width: int = 1280,
) -> dict:
    """Export a still from a clip (at=mid|start|end)."""
    return _require_editor().export_clip_still(
        clip_id, output_path, at=at, width=width,
    )


@mcp.tool()
def freeze_clip_mid(
    clip_id: str,
    duration_frames: int = 30,
    insert: bool = True,
) -> dict:
    """Freeze mid-frame of a clip; place still after clip when insert=True."""
    return _require_editor().freeze_clip_mid(
        clip_id, duration_frames=duration_frames, insert=insert,
    )


@mcp.tool()
def export_clips_pack(
    clip_ids: list[str],
    output_dir: str,
    prefix: str = "clip",
) -> dict:
    """Export each clip span as MP4 into output_dir."""
    return _require_editor().export_clips_pack(
        clip_ids, output_dir, prefix=prefix,
    )


@mcp.tool()
def add_slate(
    title: str = "SLATE",
    subtitle: str | None = None,
    duration_frames: int = 90,
    track_id: str | None = None,
    size: int = 64,
    ripple_all_tracks: bool = True,
    append: bool = False,
) -> dict:
    """Add a production slate title card (prepend by default)."""
    return _require_editor().add_slate(
        title,
        subtitle=subtitle,
        duration_frames=duration_frames,
        track_id=track_id,
        size=size,
        ripple_all_tracks=ripple_all_tracks,
        append=append,
    )


@mcp.tool()
def close_gaps_all_tracks(
    from_frame: int = 0,
    kind: str | None = None,
) -> dict:
    """Close gaps on every unlocked track (optional kind=video|audio)."""
    return _require_editor().close_gaps_all_tracks(
        from_frame=from_frame, kind=kind,
    )


@mcp.tool()
def export_track_only(
    output_path: str,
    track_id: str | None = None,
    clip_id: str | None = None,
    normalize_preset: str | None = None,
) -> dict:
    """Export full timeline with only this track unmuted (track_id or clip_id)."""
    if not track_id and not clip_id:
        raise ValueError("track_id or clip_id required")
    return _require_editor().export_track_only(
        track_id or "",
        output_path,
        normalize_preset=normalize_preset,
        clip_id=clip_id,
    )


@mcp.tool()
def export_selection_mp4(
    clip_ids: list[str],
    output_path: str,
    normalize_preset: str | None = None,
) -> dict:
    """Export the union timeline span of clips as one MP4."""
    return _require_editor().export_selection_mp4(
        clip_ids, output_path, normalize_preset=normalize_preset,
    )


@mcp.tool()
def export_work_area_mp4(
    output_path: str,
    normalize_preset: str | None = None,
) -> dict:
    """Export in/out work area as MP4."""
    return _require_editor().export_work_area_mp4(
        output_path, normalize_preset=normalize_preset,
    )


@mcp.tool()
def lift_clip(clip_id: str) -> dict:
    """Remove clip leaving a gap (Premiere Lift, no ripple)."""
    return _require_editor().lift_clip(clip_id)


@mcp.tool()
def ripple_delete_selection(clip_ids: list[str]) -> dict:
    """Ripple-delete multiple clips (end→start per track)."""
    return _require_editor().ripple_delete_selection(clip_ids)


@mcp.tool()
def copy_effects(
    source_clip_id: str,
    target_clip_ids: list[str],
    replace: bool = True,
    types: list[str] | None = None,
) -> dict:
    """Copy effects from source clip onto target clips."""
    return _require_editor().copy_effects(
        source_clip_id,
        target_clip_ids,
        replace=replace,
        types=types,
    )


@mcp.tool()
def export_clips_stills_pack(
    clip_ids: list[str],
    output_dir: str,
    at: str = "mid",
    width: int = 1280,
    prefix: str = "still",
) -> dict:
    """Export a still for each clip into output_dir."""
    return _require_editor().export_clips_stills_pack(
        clip_ids, output_dir, at=at, width=width, prefix=prefix,
    )


@mcp.tool()
def join_clips(left_clip_id: str, right_clip_id: str) -> dict:
    """Join two adjacent same-media clips on one track."""
    return _require_editor().join_clips(left_clip_id, right_clip_id)


@mcp.tool()
def paste_position(
    source_clip_id: str,
    target_clip_ids: list[str],
) -> dict:
    """Copy PiP position (x/y/scale) from source to targets."""
    return _require_editor().paste_position(source_clip_id, target_clip_ids)


@mcp.tool()
def set_clips_flip(
    clip_ids: list[str],
    horizontal: bool | None = True,
    vertical: bool | None = None,
    toggle_h: bool = False,
    toggle_v: bool = False,
) -> dict:
    """Batch set/toggle hflip/vflip on clips."""
    return _require_editor().set_clips_flip(
        clip_ids,
        horizontal=horizontal,
        vertical=vertical,
        toggle_h=toggle_h,
        toggle_v=toggle_v,
    )


@mcp.tool()
def export_webm(
    output_path: str,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    crf: int = 32,
    width: int | None = None,
) -> dict:
    """Export timeline range as WebM (VP9 + Opus)."""
    return _require_editor().export_webm(
        output_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        crf=crf,
        width=width,
    )


@mcp.tool()
def export_clip_gif(
    clip_id: str,
    output_path: str,
    fps: float = 12.0,
    width: int = 480,
    max_duration_seconds: float = 12.0,
) -> dict:
    """Export a clip's timeline span as animated GIF."""
    return _require_editor().export_clip_gif(
        clip_id,
        output_path,
        fps=fps,
        width=width,
        max_duration_seconds=max_duration_seconds,
    )


@mcp.tool()
def apply_ken_burns_to_images(
    track_id: str | None = None,
    zoom_end: float = 1.12,
    replace: bool = True,
) -> dict:
    """Apply gentle Ken Burns to all image stills (project or track)."""
    return _require_editor().apply_ken_burns_to_images(
        track_id=track_id,
        zoom_end=zoom_end,
        replace=replace,
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
def preview_engine_status() -> dict:
    """Interactive path-C engine status (libopenshot/MLT). May be unavailable.

    Until packaging ships, use ensure_preview_proxy / frame_at for interim scrub.
    See docs/SPIKE_LIBOPENSHOT_WINDOWS.md and docs/ADR_UI_AND_PREVIEW.md.
    """
    return _require_editor().preview_engine_status()


@mcp.tool()
def openshot_frame_at(
    time_seconds: float,
    output_path: str,
    height: int = 360,
    use_timeline: bool = True,
) -> dict:
    """Path-C multi-clip frame via OpenShot (needs OpenShot / OPMIERE_OPENSHOT_HOME)."""
    return _require_editor().openshot_frame_at(
        time_seconds, output_path, height=height, use_timeline=use_timeline,
    )


@mcp.tool()
def path_c_effect_catalog() -> dict:
    """What path-C (OpenShot still preview) can map vs skip for grade FX.

    Prefer mapped effects when agents need WYSIWYG program-monitor feedback.
    Unmapped effects still apply on ffmpeg export.
    """
    from .render.openshot_map import path_c_effect_catalog as _catalog

    return _catalog()


@mcp.tool()
def clip_path_c(clip_id: str) -> dict:
    """Per-clip path-C readiness for the current effect stack."""
    from .render.openshot_map import clip_path_c_support

    clip = _require_editor()._find_clip(clip_id)  # noqa: SLF001
    return clip_path_c_support(clip)


@mcp.tool()
def project_path_c() -> dict:
    """Project-wide path-C readiness: which clips have export-only FX."""
    from .render.openshot_map import project_path_c_report

    return project_path_c_report(_require_editor().project)


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
