"""The Operation API — the single mutation surface over a Project.

ARCHITECTURE.md section 4 (design principle 1) and section 7: every edit, whether
from a human GUI, an AI agent (mcp_server.py is a thin projection of this class),
or undo/redo, goes through an ``Editor``. That single choke point is what makes
undo/redo free and keeps the MCP surface a mechanical mapping of these methods.

Undo/redo is snapshot-based (whole-project JSON snapshots), not hand-written
inverses per operation. Timelines are small documents, so this is cheap, and it
sidesteps an entire class of "inverse operation got it subtly wrong" bugs that a
command-pattern-with-manual-undo approach invites.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .bundle import Bundle
from .generation.provider import GenerationJob, GenerationProvider, JobStatus
from .model import (
    CURVES_PRESETS,
    KNOWN_EFFECT_TYPES,
    KNOWN_TRANSITION_TYPES,
    SHAPE_MASK_SHAPES,
    TEXT_POSITIONS,
    Clip,
    Marker,
    Media,
    MediaKind,
    Project,
    Track,
    TrackKind,
    new_id,
)
from .render.audio_critic import analyze_audio as _analyze_audio
from .render.backend import RenderBackend
from .render.contact_sheet import make_contact_sheet as _make_contact_sheet
from .render.delivery import delivery_check as _delivery_check
from .render.delivery import normalize_loudness as _normalize_loudness
from .render.ffmpeg import FFmpegBackend
from .render.ffmpeg import import_media as _ffmpeg_import_media
from .render.beats import detect_beats as _detect_beats
from .render.hwencode import encode_status as _encode_status
from .render.look import LOOK_PRESETS as _LOOK_PRESETS
from .render.look import measure_frame_stats as _measure_frame_stats
from .render.look import resolve_look as _resolve_look
from .render.look import suggest_color_match_effects as _suggest_color_match_effects
from .render.style_presets import blend_styles as _blend_styles
from .render.style_presets import list_style_assets as _list_style_assets
from .render.style_presets import list_styles as _list_styles
from .render.style_presets import resolve_style_asset as _resolve_style_asset
from .render.style_presets import resolve_style_effects as _resolve_style_effects
from .render.cut_templates import get_template as _get_cut_template
from .render.cut_templates import list_templates as _list_cut_templates
from .recent import CLIP_COLORS as _CLIP_COLORS
from .recent import clear_recent as _clear_recent
from .recent import list_recent as _list_recent
from .recent import touch_recent as _touch_recent
from .render.mix_suggest import suggest_dialogue_chain as _suggest_dialogue_chain
from .render.mix_suggest import suggest_mix as _suggest_mix
from .render.quality_check import quality_check as _quality_check
from .render.room_tone import extract_room_tone as _extract_room_tone
from .render.room_tone import suggest_room_tone as _suggest_room_tone
from .render.sequence_review import make_sequence_contact_sheet as _make_sequence_contact_sheet
from .render.sequence_review import review_cut as _review_cut
from .render.silence_edit import suggest_keep_ranges as _suggest_keep_ranges
from .render.asr import transcribe as _transcribe
from .render.asr import write_srt as _write_srt
from .render.filler_edit import suggest_filler_cuts_from_segments as _suggest_filler_cuts
from .render.media_proxy import build_media_proxy as _build_media_proxy
from .render.transcript_index import load_transcript as _load_transcript
from .render.transcript_index import save_transcript as _save_transcript
from .render.transcript_index import search_segments as _search_segments
from .render.transcript_index import search_transcript_dict as _search_transcript_dict
from .render.waveform import extract_waveform_peaks as _extract_waveform_peaks
from .render.waveform import load_cached_peaks as _load_cached_peaks
from .render.waveform import save_cached_peaks as _save_cached_peaks
from .render.asset_analysis import analyze_asset as _analyze_asset
from .render.asset_analysis import check_delivery_limits as _check_delivery_limits
from .render.asset_analysis import load_analysis_cache as _load_analysis_cache
from .render.asset_analysis import plan_edit as _plan_edit
from .render.asset_analysis import save_analysis_cache as _save_analysis_cache
from .render.asset_analysis import suggest_project_fps as _suggest_project_fps
from .render.asset_analysis import suggest_project_resolution as _suggest_project_resolution
from .render.scene_detect import detect_scenes as _detect_scenes
from .render.stems import separate_stems as _separate_stems

# Maps a GenerationJob.kind (what an agent asked to generate) to the
# Media.kind it becomes once it's a file on disk. image/video are their own
# media kind; speech/sfx/music are all just "audio" once generated; upscale
# defaults to "image" but place_generated overrides to "video" when the
# result is a video container (frame-pipeline upscale of a multi-frame source).
_GENERATION_KIND_TO_MEDIA_KIND = {"speech": "audio", "sfx": "audio", "music": "audio", "upscale": "image"}
_VIDEO_UPSCALE_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}


class Editor:
    """Wraps a Project + Bundle. The only supported way to mutate either."""

    def __init__(
        self,
        bundle: Bundle,
        render_backend: RenderBackend | None = None,
        generation_provider: GenerationProvider | None = None,
    ):
        self.bundle = bundle
        self.project: Project = bundle.load()
        self.render_backend = render_backend or FFmpegBackend()
        self._preview_proxy_path: str | None = None
        self._preview_proxy_fingerprint: str | None = None
        # Last successful scrub settings (used by refresh_preview_proxy).
        self._preview_proxy_height: int = 360
        self._preview_proxy_fps: float = 12.0
        # No default provider: generation is optional and pluggable (section
        # 4 principle 3) - unlike rendering, there's no single obvious
        # default (local vs cloud, which model), so the caller must choose.
        self.generation_provider = generation_provider
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        # Session clipboard + work in/out (not persisted in project.json)
        self._clipboard: dict[str, Any] | None = None
        self._effects_clipboard: list[dict[str, Any]] | None = None
        self._attributes_clipboard: dict[str, Any] | None = None
        self._in_point: int | None = None
        self._out_point: int | None = None
        self._dirty: bool = False
        self._autosave: bool = False

    def _timeline_fingerprint(self) -> str:
        """Hash of timeline-relevant project state for proxy freshness."""
        blob = json.dumps(self.project.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def invalidate_preview_proxy(self) -> None:
        """Mark scrub proxy stale (path kept so status can report file exists)."""
        # Keep path for diagnostics; fingerprint None ⇒ not fresh
        self._preview_proxy_fingerprint = None

    def preview_proxy_status(self) -> dict[str, Any]:
        """Is the last export_preview still valid for this timeline?"""
        path = self._preview_proxy_path
        exists = bool(path and Path(path).exists())
        fp_now = self._timeline_fingerprint()
        fresh = (
            exists
            and self._preview_proxy_fingerprint is not None
            and self._preview_proxy_fingerprint == fp_now
        )
        return {
            "path": path if exists else None,
            "exists": exists,
            "fresh": fresh,
            "fingerprint": self._preview_proxy_fingerprint,
            "timeline_fingerprint": fp_now,
            "agent_note": (
                "Proxy is current — frame_at prefer_proxy is safe."
                if fresh
                else (
                    "Proxy stale after timeline edit — re-run export_preview."
                    if exists
                    else "No proxy — call export_preview for full-timeline scrub."
                )
            ),
        }

    @classmethod
    def create(
        cls,
        root: Path,
        fps: float = 30.0,
        width: int = 1920,
        height: int = 1080,
        generation_provider: GenerationProvider | None = None,
    ) -> "Editor":
        # Default 30 for social/delivery clarity; use suggest_project_fps()
        # when user footage is nearer 24. Avoid defaulting to gen-model 16fps.
        project = Project()
        project.timebase.fps = fps
        project.resolution.w, project.resolution.h = width, height
        bundle = Bundle.create(Path(root), project=project)
        ed = cls(bundle, generation_provider=generation_provider)
        ed._dirty = False
        try:
            _touch_recent(bundle.root)
        except OSError:
            pass
        return ed

    @classmethod
    def open(cls, root: Path, generation_provider: GenerationProvider | None = None) -> "Editor":
        ed = cls(Bundle.open(Path(root)), generation_provider=generation_provider)
        ed._dirty = False
        try:
            _touch_recent(ed.bundle.root)
        except OSError:
            pass
        return ed

    def save(self) -> None:
        self.bundle.save(self.project)
        self._dirty = False
        try:
            _touch_recent(self.bundle.root)
        except OSError:
            pass

    def is_dirty(self) -> bool:
        return bool(self._dirty)

    def set_autosave(self, enabled: bool = True) -> dict[str, Any]:
        self._autosave = bool(enabled)
        return {"autosave": self._autosave, "dirty": self._dirty}

    def list_recent_projects(self, limit: int = 12) -> dict[str, Any]:
        return _list_recent(limit=limit)

    def clear_recent_projects(self) -> dict[str, Any]:
        return _clear_recent()

    def set_clip_meta(
        self,
        clip_id: str,
        *,
        name: str | None = None,
        color: str | None = None,
        clear_name: bool = False,
        clear_color: bool = False,
    ) -> dict[str, Any]:
        """Set display name / color chip on a clip (not rendered into pixels)."""
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            if clear_name:
                clip.name = None
            elif name is not None:
                clip.name = str(name).strip() or None
            if clear_color:
                clip.color = None
            elif color is not None:
                c = str(color).strip()
                if c and not c.startswith("#"):
                    c = "#" + c
                clip.color = c or None
            return {
                "clip_id": clip_id,
                "name": clip.name,
                "color": clip.color,
                "palette": list(_CLIP_COLORS),
            }

    def list_clip_colors(self) -> dict[str, Any]:
        return {"colors": list(_CLIP_COLORS)}

    def set_project_notes(self, notes: str) -> dict[str, Any]:
        """Free-text project notes (persisted in project.json, not in pixels)."""
        with self._mutate():
            self.project.notes = str(notes or "")
            return {"notes": self.project.notes, "length": len(self.project.notes)}

    def get_project_notes(self) -> dict[str, Any]:
        return {"notes": self.project.notes or ""}

    @staticmethod
    def get_keymap_help(_self: Any = None) -> dict[str, Any]:
        """Document web/NLE keyboard shortcuts for agents and the help overlay."""
        return {
            "shortcuts": [
                {"keys": "Space", "action": "Play/pause proxy"},
                {"keys": "← / →", "action": "Step frame (Shift = 1s)"},
                {"keys": "Alt+← / Alt+→", "action": "Ripple nudge selection"},
                {"keys": "M", "action": "Add marker at playhead"},
                {"keys": "S", "action": "Split selected (+ linked peers)"},
                {"keys": "C", "action": "Razor all tracks at playhead"},
                {"keys": "Shift+J / Shift+L", "action": "J-cut / L-cut linked audio ±15f"},
                {"keys": "I / O", "action": "Set work In / Out"},
                {"keys": "Ctrl+C/V/D", "action": "Copy / paste / duplicate"},
                {"keys": "Ctrl+Shift+V", "action": "Overwrite paste at playhead"},
                {"keys": "J / K / L", "action": "Shuttle: reverse / stop / play (repeat L speeds up)"},
                {"keys": "U", "action": "Subclip from work In/Out (selected clip)"},
                {"keys": "Q", "action": "Ripple trim head to playhead (+ linked)"},
                {"keys": "W", "action": "Ripple trim tail to playhead (+ linked)"},
                {"keys": "Shift+T", "action": "Fit-to-fill selected (stretch to next / Out)"},
                {"keys": ", / .", "action": "Slip selected −/+ 5 source frames"},
                {"keys": "; / '", "action": "Slide selected −/+ 5 frames"},
                {"keys": "Shift+M", "action": "Jump to next marker"},
                {"keys": "G", "action": "Close all track gaps"},
                {"keys": "R", "action": "Reset transform on selection (PiP/crop/rotate/opacity)"},
                {"keys": "Ctrl+L", "action": "Link selected clips"},
                {"keys": "Ctrl+Shift+L", "action": "Select entire link group"},
                {"keys": "\\", "action": "Zoom timeline to fit"},
                {"keys": "A", "action": "Select all clips on selected clip's track"},
                {"keys": "Del", "action": "Ripple delete selection"},
                {"keys": "[ / ]", "action": "Undo / redo"},
                {"keys": "F", "action": "Fill base gaps (black)"},
                {"keys": "Shift+F", "action": "Match frame (source of selection at playhead)"},
                {"keys": "Ctrl+click", "action": "Multi-select clips"},
                {"keys": "Shift+click", "action": "Range select on track"},
                {"keys": "?", "action": "Toggle this help"},
            ],
            "agent_note": "Human web shell only; MCP uses tools, not key events.",
        }

    # --- read-only introspection (what an agent queries before it acts) ----
    def describe(self) -> dict:
        return self.project.to_dict()

    def duration_frames(self) -> int:
        return self.project.duration_frames()

    def timeline_view(self) -> dict[str, Any]:
        """UI/agent-friendly timeline: seconds, clip layout, media labels, proxy.

        Complements describe() with layout metrics for proportional tracks and
        scrub players. Read-only — no mutation.
        """
        fps = float(self.project.timebase.fps or 30.0)
        media_by_id = {m.id: m for m in self.project.media}
        tracks_out: list[dict[str, Any]] = []
        max_end = 0
        for track in self.project.tracks:
            clips_out: list[dict[str, Any]] = []
            for clip in track.clips_in_order():
                m = media_by_id.get(clip.media)
                end = clip.end
                max_end = max(max_end, end)
                gain_db = 0.0
                fade_in_f = 0
                fade_out_f = 0
                opacity = 1.0
                for fx in clip.effects or []:
                    if fx.get("type") == "gain" and isinstance(fx.get("db"), (int, float)):
                        gain_db = float(fx["db"])
                    if fx.get("type") == "fade" and isinstance(fx.get("duration_frames"), int):
                        if fx.get("direction") == "in":
                            fade_in_f = int(fx["duration_frames"])
                        elif fx.get("direction") == "out":
                            fade_out_f = int(fx["duration_frames"])
                    if fx.get("type") == "opacity" and isinstance(fx.get("amount"), (int, float)):
                        opacity = float(fx["amount"])
                clips_out.append({
                    "id": clip.id,
                    "media_id": clip.media,
                    "media_path": m.path if m else None,
                    "media_kind": m.kind if m else None,
                    "start_frame": clip.start,
                    "end_frame": end,
                    "duration_frames": clip.timeline_duration_frames,
                    "start_seconds": round(clip.start / fps, 3),
                    "end_seconds": round(end / fps, 3),
                    "duration_seconds": round(clip.timeline_duration_frames / fps, 3),
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "speed": clip.speed,
                    "effects_count": len(clip.effects or []),
                    "gain_db": gain_db,
                    "fade_in_frames": fade_in_f,
                    "fade_out_frames": fade_out_f,
                    "opacity": opacity,
                    "muted": bool(clip.muted),
                    "has_audio_media": bool(m and (m.kind == "audio" or m.has_audio)),
                    "transition_in": clip.transition_in,
                    "name": clip.name,
                    "color": clip.color,
                    "position": clip.position,
                    "link_group": clip.link_group,
                    "label": (
                        clip.name
                        or (m.path.split("/")[-1] if m and m.path else clip.id)
                    ),
                })
            tracks_out.append({
                "id": track.id,
                "kind": track.kind,
                "name": track.name,
                "clip_count": len(clips_out),
                "clips": clips_out,
                "duck": track.duck,
                "muted": bool(track.muted),
                "solo": bool(track.solo),
                "locked": bool(track.locked),
            })
        duration_frames = max_end
        duration_seconds = round(duration_frames / fps, 3) if fps else 0.0
        proxy = self.preview_proxy_status()
        return {
            "project_id": self.project.id,
            "fps": fps,
            "width": self.project.resolution.w,
            "height": self.project.resolution.h,
            "duration_frames": duration_frames,
            "duration_seconds": duration_seconds,
            "tracks": tracks_out,
            "media_count": len(self.project.media),
            "proxy": proxy,
            "can_undo": bool(self._undo_stack),
            "can_redo": bool(self._redo_stack),
            "mix": self.mix_view(),
            "markers": self.list_markers()["markers"],
            "snap_frames": self.snap_points()["frames"],
            "work_in_out": self.get_in_out(),
            "clipboard": (
                {"has": True, "media_id": self._clipboard.get("media")}
                if self._clipboard else {"has": False}
            ),
            "dirty": self._dirty,
            "autosave": self._autosave,
            "bundle_path": str(self.bundle.root),
            "notes": self.project.notes or "",
        }

    # --- undo/redo -----------------------------------------------------
    def _snapshot(self) -> dict:
        """Deep snapshot of project JSON (effects/lists must not share refs)."""
        return json.loads(json.dumps(self.project.to_dict(), ensure_ascii=False))

    @contextmanager
    def _mutate(self) -> Iterator[None]:
        """Snapshot before a mutation; roll the snapshot back if it fails."""
        self._undo_stack.append(self._snapshot())
        try:
            yield
        except Exception:
            self._undo_stack.pop()
            raise
        else:
            self._redo_stack.clear()
            # Timeline changed — scrub proxy no longer matches
            self.invalidate_preview_proxy()
            self._dirty = True
            if self._autosave:
                try:
                    self.save()
                except OSError:
                    pass

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self.project = Project.from_dict(self._undo_stack.pop())
        self.invalidate_preview_proxy()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self.project = Project.from_dict(self._redo_stack.pop())
        self.invalidate_preview_proxy()
        return True

    # --- lookup helpers -------------------------------------------------
    def _find_clip_and_track(self, clip_id: str) -> tuple[Track, Clip]:
        for track in self.project.tracks:
            for clip in track.clips:
                if clip.id == clip_id:
                    return track, clip
        raise KeyError(f"no clip with id {clip_id!r}")

    def _find_clip(self, clip_id: str) -> Clip:
        return self._find_clip_and_track(clip_id)[1]

    # --- operations (section 7) ------------------------------------------
    def import_media(
        self,
        src_path: Path,
        kind: MediaKind,
        *,
        conform: bool = True,
        fit: str = "none",
        origin: dict[str, Any] | None = None,
        build_proxy: bool = False,
        proxy_height: int = 480,
    ) -> Media:
        """Import media.

        conform=True: re-encode when source fps ≠ project.
        fit: none | contain (letterbox) | cover (crop-fill) to project resolution.
        build_proxy=True: also encode a low-res asset proxy under proxies/ (video).
        """
        with self._mutate():
            media = _ffmpeg_import_media(
                self.bundle,
                self.project,
                Path(src_path),
                kind,
                origin=origin,
                conform=conform,
                fit=fit,
            )
        if build_proxy and kind == "video":
            try:
                self.ensure_media_proxy(media.id, height=proxy_height)
            except Exception as e:
                # Import must not fail because proxy encode failed.
                media = self.project.media_by_id(media.id)
                if media.origin is None:
                    media.origin = {}
                media.origin = dict(media.origin)
                media.origin["proxy_error"] = str(e)[:500]
                self.save()
        return self.project.media_by_id(media.id)

    def list_media_bin(self) -> dict[str, Any]:
        """Media bin status: source paths, proxy readiness, transcript cache."""
        items: list[dict[str, Any]] = []
        for m in self.project.media:
            proxy_abs = None
            proxy_ready = False
            if m.proxy_path:
                proxy_abs = self.bundle.resolve_bundle_path(m.proxy_path)
                proxy_ready = proxy_abs.exists()
            tr = _load_transcript(self.bundle.analysis_dir, m.id)
            items.append({
                "id": m.id,
                "kind": m.kind,
                "path": m.path,
                "abs_path": str(self.bundle.media_path(m.path)),
                "duration_frames": m.duration_frames,
                "has_audio": m.has_audio,
                "proxy_path": m.proxy_path,
                "proxy_ready": proxy_ready,
                "proxy_abs": str(proxy_abs) if proxy_abs else None,
                "transcript_cached": tr is not None,
                "transcript_segments": (
                    len(tr.get("segments") or []) if tr else 0
                ),
            })
        return {
            "count": len(items),
            "media": items,
            "agent_note": (
                "Per-asset proxies (ensure_media_proxy) for bin scrub; "
                "timeline preview is separate (ensure_preview_proxy)."
            ),
        }

    def ensure_media_proxy(
        self,
        media_id: str,
        *,
        height: int = 480,
        force: bool = False,
    ) -> dict[str, Any]:
        """Build or reuse a low-res proxy for one media asset (video preferred)."""
        media = self.project.media_by_id(media_id)
        if media.kind == "audio":
            raise ValueError("audio-only media has no video proxy; use waveform tools")
        if media.proxy_path and not force:
            existing = self.bundle.resolve_bundle_path(media.proxy_path)
            if existing.exists():
                return {
                    "media_id": media_id,
                    "path": str(existing),
                    "proxy_path": media.proxy_path,
                    "cache_hit": True,
                    "fresh": True,
                }
        src = self.bundle.media_path(media.path)
        if not src.exists():
            raise FileNotFoundError(src)
        self.bundle.proxies_dir.mkdir(parents=True, exist_ok=True)
        dest = self.bundle.proxies_dir / f"{media_id}.mp4"
        report = _build_media_proxy(src, dest, height=height, audio=media.has_audio)
        rel = dest.relative_to(self.bundle.root).as_posix()
        with self._mutate():
            m = self.project.media_by_id(media_id)
            m.proxy_path = rel
        return {
            "media_id": media_id,
            "path": report["path"],
            "proxy_path": rel,
            "cache_hit": False,
            "width": report.get("width"),
            "height": report.get("height"),
            "duration_seconds": report.get("duration_seconds"),
            "agent_note": "Asset proxy for bin scrub — not delivery master.",
        }

    def ensure_all_media_proxies(
        self,
        *,
        height: int = 480,
        force: bool = False,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build proxies for all video/image media missing one."""
        kinds_set = set(kinds or ["video"])
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for m in list(self.project.media):
            if m.kind not in kinds_set:
                continue
            if m.kind == "image":
                # stills: skip proxy encode (cheap to load full)
                results.append({
                    "media_id": m.id,
                    "skipped": True,
                    "reason": "image — use full still",
                })
                continue
            try:
                results.append(
                    self.ensure_media_proxy(m.id, height=height, force=force)
                )
            except Exception as e:
                errors.append({"media_id": m.id, "error": str(e)[:400]})
        return {
            "built": [r for r in results if not r.get("skipped") and not r.get("cache_hit")],
            "cache_hits": [r for r in results if r.get("cache_hit")],
            "skipped": [r for r in results if r.get("skipped")],
            "errors": errors,
            "count": len(results),
        }

    def add_track(self, kind: TrackKind) -> Track:
        with self._mutate():
            return self.project.add_track(kind)

    def delete_track(self, track_id: str) -> Track:
        """Remove a track and every clip on it. Undoable like any mutation.

        Also clears any *other* track's duck-against reference to this track —
        leaving a dangling reference would make every later export fail on a
        track the user already decided to throw away.
        """
        with self._mutate():
            track = self.project.track_by_id(track_id)
            self.project.tracks.remove(track)
            for other in self.project.tracks:
                if other.duck is not None and other.duck.get("against") == track_id:
                    other.duck = None
            return track

    def add_clip(
        self, track_id: str, media_id: str, start: int, src_in: int, src_out: int
    ) -> Clip:
        with self._mutate():
            track = self.project.track_by_id(track_id)
            media = self.project.media_by_id(media_id)
            return self.project.add_clip(track, media, start, src_in, src_out)

    def place_from_file(
        self,
        src_path: Path,
        kind: MediaKind,
        track_id: str,
        start: int,
        duration_frames: int | None = None,
        origin: dict[str, Any] | None = None,
        *,
        conform: bool = True,
        fit: str = "none",
    ) -> Clip:
        """Import a local file and place it as a clip in one operation.

        The local-file twin of place_generated, with the same duration rule:
        omit duration_frames to use the media's full real (ffprobed) duration
        — the common case when placing a whole song/voiceover/shot — but it
        stays required for kind="image" (no intrinsic duration to fall back
        on). One operation instead of import_media + add_clip also means one
        undo step, matching what "place this file" means to the caller.

        Video sources whose fps ≠ project timebase are re-encoded into the
        bundle when ``conform=True`` (default). ``fit`` contain/cover scales
        into project resolution at import time.

        ``origin`` lets provenance survive a process restart: place_generated
        needs the provider's in-memory job, so a finished job's result_path
        placed from a *later* session comes through here instead — pass the
        provider/job/prompt (and license) metadata yourself and the Media
        record stays as auditable as if place_generated had done it.
        """
        if duration_frames is not None and duration_frames <= 0:
            raise ValueError(f"duration_frames must be positive, got {duration_frames}")
        if duration_frames is None and kind == "image":
            # Checked before the import, not after: _mutate rolls back the
            # *project* on failure but a file already copied into the
            # bundle's media/ dir stays there, and retrying would then hit
            # "media file already exists in bundle".
            raise ValueError(
                "duration_frames is required for kind='image' "
                "(images have no intrinsic duration)"
            )
        with self._mutate():
            track = self.project.track_by_id(track_id)
            media = _ffmpeg_import_media(
                self.bundle,
                self.project,
                Path(src_path),
                kind,
                origin=origin,
                conform=conform,
                fit=fit,
            )
            if duration_frames is None:
                duration_frames = media.duration_frames
            return self.project.add_clip(track, media, start, 0, duration_frames)

    @staticmethod
    def guess_media_kind(path: Path | str) -> MediaKind:
        """Infer media kind from file suffix (fallback: video)."""
        suf = Path(path).suffix.lower()
        if suf in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}:
            return "audio"
        if suf in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}:
            return "image"
        return "video"

    def place_batch(
        self,
        paths: list[str | Path],
        *,
        kind: MediaKind | None = None,
        track_id: str | None = None,
        start: int | None = None,
        sequential: bool = True,
        conform: bool = True,
        fit: str = "none",
        build_proxy: bool = False,
        image_duration_frames: int = 90,
    ) -> dict[str, Any]:
        """Import and place many local files (batch bin → timeline).

        sequential=True places each clip after the previous on the same track.
        kind=None auto-detects per file (audio/image/video by suffix).
        track_id=None creates/uses first track matching the *first* item's kind
        (mixed video+audio batches: video goes to video track; audio to audio).
        """
        if not paths:
            raise ValueError("paths is empty")
        placed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        # Cursor per track for sequential append
        cursors: dict[str, int] = {}
        first_start = 0 if start is None else int(start)

        for raw in paths:
            p = Path(raw)
            try:
                item_kind: MediaKind = kind or self.guess_media_kind(p)
                track_kind: TrackKind = "audio" if item_kind == "audio" else "video"
                tid = track_id
                if tid is None:
                    existing = [t for t in self.project.tracks if t.kind == track_kind]
                    if existing:
                        tid = existing[0].id
                    else:
                        tid = self.add_track(track_kind).id
                if sequential:
                    if tid not in cursors:
                        track = self.project.track_by_id(tid)
                        ordered = track.clips_in_order()
                        if ordered and start is None:
                            cursors[tid] = ordered[-1].end
                        else:
                            cursors[tid] = first_start
                    clip_start = cursors[tid]
                else:
                    clip_start = first_start

                dur: int | None = None
                if item_kind == "image":
                    dur = int(image_duration_frames)

                if build_proxy and item_kind == "video":
                    media = self.import_media(
                        p, item_kind, conform=conform, fit=fit, build_proxy=True,
                    )
                    clip = self.add_clip(
                        tid, media.id, clip_start, 0,
                        dur if dur is not None else media.duration_frames,
                    )
                else:
                    clip = self.place_from_file(
                        p, item_kind, tid, clip_start,
                        duration_frames=dur,
                        conform=conform,
                        fit=fit,
                    )
                if sequential:
                    cursors[tid] = clip.end
                placed.append({
                    "path": str(p),
                    "clip_id": clip.id,
                    "media_id": clip.media,
                    "track_id": tid,
                    "kind": item_kind,
                    "start": clip.start,
                    "end": clip.end,
                })
            except Exception as e:
                errors.append({"path": str(p), "error": str(e)[:400]})

        return {
            "placed_count": len(placed),
            "error_count": len(errors),
            "placed": placed,
            "errors": errors,
            "agent_note": (
                "Batch place complete. Review errors; base video track must "
                "stay contiguous from frame 0 for export."
            ),
        }

    def mix_view(self) -> dict[str, Any]:
        """Mix console snapshot: audio tracks, per-clip gains, ducking graph."""
        audio_tracks: list[dict[str, Any]] = []
        video_tracks: list[dict[str, Any]] = []
        for track in self.project.tracks:
            clips_info: list[dict[str, Any]] = []
            for clip in track.clips_in_order():
                media = self.project.media_by_id(clip.media)
                gain = 0.0
                for fx in clip.effects or []:
                    if fx.get("type") == "gain" and isinstance(fx.get("db"), (int, float)):
                        gain = float(fx["db"])
                clips_info.append({
                    "clip_id": clip.id,
                    "media_id": clip.media,
                    "label": media.path.split("/")[-1] if media.path else clip.id,
                    "start": clip.start,
                    "end": clip.end,
                    "gain_db": gain,
                })
            entry = {
                "track_id": track.id,
                "kind": track.kind,
                "clip_count": len(clips_info),
                "clips": clips_info,
                "duck": track.duck,
            }
            if track.kind == "audio":
                audio_tracks.append(entry)
            else:
                video_tracks.append(entry)

        duck_edges = []
        for t in audio_tracks:
            if t.get("duck") and t["duck"].get("against"):
                duck_edges.append({
                    "from": t["track_id"],
                    "against": t["duck"]["against"],
                    "threshold_db": t["duck"].get("threshold_db"),
                    "ratio": t["duck"].get("ratio"),
                })

        return {
            "audio_tracks": audio_tracks,
            "video_tracks": video_tracks,
            "duck_edges": duck_edges,
            "audio_track_count": len(audio_tracks),
            "agent_note": (
                "Duck: music track ducks under VO (against=vo). "
                "set_ducking(music_id, vo_id); clear_ducking(music_id)."
            ),
        }

    def _assert_clip_track_unlocked(self, clip_id: str) -> Track:
        track, _ = self._find_clip_and_track(clip_id)
        if track.locked:
            raise ValueError(f"track {track.id} is locked — unlock to edit")
        return track

    def set_track_muted(self, track_id: str, muted: bool = True) -> dict[str, Any]:
        with self._mutate():
            track = self.project.track_by_id(track_id)
            track.muted = bool(muted)
            return {"track_id": track_id, "muted": track.muted, "solo": track.solo, "locked": track.locked}

    def set_track_solo(
        self,
        track_id: str,
        solo: bool = True,
        *,
        exclusive: bool = False,
    ) -> dict[str, Any]:
        """Solo a track. exclusive=True clears solo on all other tracks of same kind."""
        with self._mutate():
            track = self.project.track_by_id(track_id)
            if exclusive and solo:
                for t in self.project.tracks:
                    if t.kind == track.kind:
                        t.solo = t.id == track_id
            else:
                track.solo = bool(solo)
            return {
                "track_id": track_id,
                "muted": track.muted,
                "solo": track.solo,
                "locked": track.locked,
                "exclusive": bool(exclusive and solo),
                "solos": [
                    {"track_id": t.id, "solo": t.solo}
                    for t in self.project.tracks
                    if t.kind == track.kind
                ],
            }

    def set_track_locked(self, track_id: str, locked: bool = True) -> dict[str, Any]:
        with self._mutate():
            track = self.project.track_by_id(track_id)
            track.locked = bool(locked)
            return {"track_id": track_id, "muted": track.muted, "solo": track.solo, "locked": track.locked}

    def set_clip_muted(self, clip_id: str, muted: bool = True) -> dict[str, Any]:
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            clip.muted = bool(muted)
            return {"clip_id": clip_id, "muted": clip.muted}

    def _expand_link_ids(self, clip_ids: list[str]) -> list[str]:
        """Union selection with every clip sharing a link_group of a selected clip."""
        ids = list(dict.fromkeys(clip_ids))
        groups: set[str] = set()
        for cid in ids:
            clip = self._find_clip(cid)
            if clip.link_group:
                groups.add(clip.link_group)
        if not groups:
            return ids
        extra: list[str] = []
        for track in self.project.tracks:
            for c in track.clips:
                if c.link_group in groups and c.id not in ids:
                    extra.append(c.id)
        return ids + extra

    def link_clips(
        self,
        clip_ids: list[str],
        *,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign clips to one link_group (NLE linked selection / A-V pair)."""
        if len(clip_ids) < 2:
            raise ValueError("link_clips needs at least 2 clip_ids")
        ids = list(dict.fromkeys(clip_ids))
        gid = group_id or new_id("lnk")
        with self._mutate():
            for cid in ids:
                self._assert_clip_track_unlocked(cid)
                clip = self._find_clip(cid)
                clip.link_group = gid
            return {
                "link_group": gid,
                "clip_ids": ids,
                "count": len(ids),
                "agent_note": "Linked for selection/nudge/delete when follow_links=True.",
            }

    def unlink_clips(self, clip_ids: list[str] | None = None) -> dict[str, Any]:
        """Clear link_group. clip_ids=None clears every linked clip."""
        with self._mutate():
            cleared: list[str] = []
            if clip_ids is None:
                targets = [
                    c for t in self.project.tracks for c in t.clips if c.link_group
                ]
            else:
                targets = [self._find_clip(cid) for cid in dict.fromkeys(clip_ids)]
            for clip in targets:
                if clip.link_group:
                    clip.link_group = None
                    cleared.append(clip.id)
            return {"cleared": cleared, "count": len(cleared)}

    def linked_group(self, clip_id: str) -> dict[str, Any]:
        """Return all clips sharing this clip's link_group (incl. self)."""
        clip = self._find_clip(clip_id)
        if not clip.link_group:
            return {
                "clip_id": clip_id,
                "link_group": None,
                "clip_ids": [clip_id],
                "count": 1,
                "linked": False,
            }
        members: list[dict[str, Any]] = []
        for track in self.project.tracks:
            for c in track.clips:
                if c.link_group == clip.link_group:
                    members.append({
                        "clip_id": c.id,
                        "track_id": track.id,
                        "track_kind": track.kind,
                        "start": c.start,
                        "end": c.end,
                    })
        return {
            "clip_id": clip_id,
            "link_group": clip.link_group,
            "clip_ids": [m["clip_id"] for m in members],
            "members": members,
            "count": len(members),
            "linked": True,
        }

    def frames_to_tc(self, frame: int) -> dict[str, Any]:
        """Format absolute frame as HH:MM:SS:FF (non-drop, project fps)."""
        if not isinstance(frame, int):
            raise ValueError("frame must be an int")
        fps = float(self.project.timebase.fps or 30.0)
        fps_i = max(1, int(round(fps)))
        f = max(0, int(frame))
        ff = f % fps_i
        total_s = f // fps_i
        ss = total_s % 60
        mm = (total_s // 60) % 60
        hh = total_s // 3600
        tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
        return {
            "frame": f,
            "tc": tc,
            "fps": fps,
            "seconds": round(f / fps, 6),
        }

    def tc_to_frames(self, tc: str) -> dict[str, Any]:
        """Parse HH:MM:SS:FF or HH:MM:SS.mmm / seconds float string → frame."""
        if not isinstance(tc, str) or not tc.strip():
            raise ValueError("tc must be a non-empty string")
        s = tc.strip()
        fps = float(self.project.timebase.fps or 30.0)
        fps_i = max(1, int(round(fps)))
        # HH:MM:SS:FF
        parts = s.replace(";", ":").split(":")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            hh, mm, ss, ff = (int(p) for p in parts)
            frame = ((hh * 3600 + mm * 60 + ss) * fps_i) + ff
            return {"tc": s, "frame": frame, "fps": fps}
        # HH:MM:SS.mmm or float seconds
        try:
            if s.count(":") == 2:
                hms, *frac = s.split(".")
                hh, mm, ss = (int(x) for x in hms.split(":"))
                frac_s = float("0." + frac[0]) if frac else 0.0
                seconds = hh * 3600 + mm * 60 + ss + frac_s
            else:
                seconds = float(s)
        except ValueError as e:
            raise ValueError(f"unrecognized timecode {tc!r}") from e
        frame = int(round(seconds * fps))
        return {"tc": s, "frame": frame, "fps": fps, "seconds": seconds}

    def nudge_clips(
        self,
        clip_ids: list[str],
        delta_frames: int,
        *,
        follow_links: bool = True,
    ) -> dict[str, Any]:
        """Move many clips by the same timeline delta (one undo). Clamped to ≥0.

        follow_links=True expands selection to full link groups.
        """
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        if not isinstance(delta_frames, int):
            raise ValueError("delta_frames must be an int")
        ids = self._expand_link_ids(clip_ids) if follow_links else list(dict.fromkeys(clip_ids))
        with self._mutate():
            moved: list[dict[str, Any]] = []
            for cid in ids:
                track, clip = self._find_clip_and_track(cid)
                if track.locked:
                    raise ValueError(f"track {track.id} is locked")
                old = clip.start
                clip.start = max(0, old + delta_frames)
                moved.append({
                    "clip_id": cid,
                    "from": old,
                    "to": clip.start,
                    "track_id": track.id,
                })
            return {
                "delta_frames": delta_frames,
                "moved": moved,
                "count": len(moved),
                "follow_links": follow_links,
            }

    def ripple_nudge(
        self,
        clip_id: str,
        delta_frames: int,
        *,
        include_self: bool = True,
    ) -> dict[str, Any]:
        """Move this clip and every later clip on the same track by delta.

        Keeps relative packing (magnetic-style). Negative delta clamped so
        the leftmost moved clip does not go below 0.
        """
        if not isinstance(delta_frames, int):
            raise ValueError("delta_frames must be an int")
        if delta_frames == 0:
            return {"clip_id": clip_id, "delta_frames": 0, "moved": [], "count": 0}
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            if track.locked:
                raise ValueError(f"track {track.id} is locked")
            targets = [
                c for c in track.clips_in_order()
                if c.start > clip.start or (include_self and c.id == clip.id)
            ]
            if not include_self:
                targets = [c for c in targets if c.id != clip.id]
            if not targets:
                return {"clip_id": clip_id, "delta_frames": 0, "moved": [], "count": 0}
            min_start = min(c.start for c in targets)
            d = delta_frames
            if min_start + d < 0:
                d = -min_start
            moved: list[dict[str, Any]] = []
            for c in targets:
                old = c.start
                c.start = old + d
                # clear transition into a clip that slid (overlap math gets messy)
                if c.transition_in is not None and c.id != clip.id:
                    c.transition_in = None
                moved.append({"clip_id": c.id, "from": old, "to": c.start})
            return {
                "clip_id": clip_id,
                "track_id": track.id,
                "delta_frames": d,
                "moved": moved,
                "count": len(moved),
                "agent_note": "Ripple nudge: self + later clips on track; transitions cleared on followers.",
            }

    def insert_time(
        self,
        track_id: str,
        at_frame: int,
        frames: int,
    ) -> dict[str, Any]:
        """Push all clips starting at/after at_frame to the right by frames.

        Opens a hole (then fill_track_gaps if you need black/silence).
        """
        if not isinstance(at_frame, int) or at_frame < 0:
            raise ValueError("at_frame must be >= 0")
        if not isinstance(frames, int) or frames <= 0:
            raise ValueError("frames must be a positive int")
        with self._mutate():
            track = self.project.track_by_id(track_id)
            if track.locked:
                raise ValueError(f"track {track.id} is locked")
            moved: list[dict[str, Any]] = []
            for c in track.clips_in_order():
                if c.start >= at_frame:
                    old = c.start
                    c.start = old + frames
                    if c.transition_in is not None:
                        c.transition_in = None
                    moved.append({"clip_id": c.id, "from": old, "to": c.start})
            return {
                "track_id": track_id,
                "at_frame": at_frame,
                "frames": frames,
                "moved": moved,
                "count": len(moved),
                "agent_note": "Gap opened; call fill_track_gaps(mode=slug) for black/silence pads.",
            }

    def _extract_time_unlocked(
        self,
        track_id: str,
        start_frame: int,
        end_frame: int,
        *,
        ripple: bool = True,
    ) -> dict[str, Any]:
        """Extract [start, end) on one track. Caller must hold ``_mutate``."""
        if end_frame <= start_frame:
            raise ValueError("end_frame must be > start_frame")
        gap = end_frame - start_frame
        track = self.project.track_by_id(track_id)
        if track.locked:
            raise ValueError(f"track {track.id} is locked")
        removed: list[str] = []
        trimmed: list[dict[str, Any]] = []

        # 1) Clips that fully span the range → split out the middle
        for clip in list(track.clips_in_order()):
            if clip.start < start_frame and clip.end > end_frame:
                left, mid = self._split_clip_unlocked(clip.id, start_frame)
                if mid.start < end_frame < mid.end:
                    mid_clip, _right = self._split_clip_unlocked(mid.id, end_frame)
                    track.clips.remove(mid_clip)
                    removed.append(mid_clip.id)
                elif mid.end <= end_frame:
                    track.clips.remove(mid)
                    removed.append(mid.id)

        # 2) Fully inside → remove
        for clip in list(track.clips_in_order()):
            if clip.start >= start_frame and clip.end <= end_frame:
                track.clips.remove(clip)
                removed.append(clip.id)

        # 3) Partial overlaps (head or tail only)
        for clip in list(track.clips_in_order()):
            c_end = clip.end
            if c_end <= start_frame or clip.start >= end_frame:
                continue
            if clip.start < start_frame < c_end:
                local = start_frame - clip.start
                if clip.speed != 1.0:
                    new_out = clip.src_in + int(round(local * clip.speed))
                else:
                    new_out = clip.src_in + local
                new_out = max(clip.src_in + 1, min(new_out, clip.src_out))
                old_out = clip.src_out
                clip.src_out = new_out
                trimmed.append({
                    "clip_id": clip.id, "edge": "tail",
                    "src_out": {"from": old_out, "to": new_out},
                })
            elif clip.start < end_frame <= c_end and clip.start >= start_frame:
                local = end_frame - clip.start
                if clip.speed != 1.0:
                    new_in = clip.src_in + int(round(local * clip.speed))
                else:
                    new_in = clip.src_in + local
                new_in = min(clip.src_out - 1, max(new_in, clip.src_in))
                clip.src_in = new_in
                clip.start = end_frame
                trimmed.append({
                    "clip_id": clip.id, "edge": "head", "start": clip.start,
                })

        if ripple and gap > 0:
            for c in track.clips_in_order():
                if c.start >= end_frame:
                    c.start = max(0, c.start - gap)
                    if c.transition_in is not None:
                        c.transition_in = None

        return {
            "track_id": track_id,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "removed": removed,
            "trimmed": trimmed,
            "ripple": ripple,
            "agent_note": "Time extracted; use fill_track_gaps if holes remain without ripple.",
        }

    def extract_time(
        self,
        track_id: str,
        start_frame: int,
        end_frame: int,
        *,
        ripple: bool = True,
    ) -> dict[str, Any]:
        """Delete the time range [start, end) on one track.

        Clips fully inside are removed. Clips overlapping the range are trimmed
        (head/tail). With ripple=True, later clips pull left by (end-start).
        """
        with self._mutate():
            return self._extract_time_unlocked(
                track_id, start_frame, end_frame, ripple=ripple,
            )

    def set_clips_muted(self, clip_ids: list[str], muted: bool = True) -> dict[str, Any]:
        """Mute/unmute many clips (one undo)."""
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        with self._mutate():
            out: list[dict[str, Any]] = []
            for cid in clip_ids:
                track, clip = self._find_clip_and_track(cid)
                if track.locked:
                    raise ValueError(f"track {track.id} is locked")
                clip.muted = bool(muted)
                out.append({"clip_id": cid, "muted": clip.muted})
            return {"muted": bool(muted), "clips": out, "count": len(out)}

    def delete_clips(
        self,
        clip_ids: list[str],
        *,
        ripple: bool = False,
        follow_links: bool = True,
    ) -> dict[str, Any]:
        """Delete many clips. ripple=True closes holes per track (right→left).

        follow_links=True also deletes peers in the same link_group.
        """
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        ids = (
            self._expand_link_ids(clip_ids)
            if follow_links
            else list(dict.fromkeys(clip_ids))
        )
        if not ripple:
            with self._mutate():
                deleted: list[str] = []
                for cid in ids:
                    track, clip = self._find_clip_and_track(cid)
                    if track.locked:
                        raise ValueError(f"track {track.id} is locked")
                    track.clips.remove(clip)
                    deleted.append(cid)
                return {"deleted": deleted, "ripple": False, "count": len(deleted)}

        # Ripple: process each track independently, highest start first
        with self._mutate():
            by_track: dict[str, list] = {}
            for cid in ids:
                track, clip = self._find_clip_and_track(cid)
                if track.locked:
                    raise ValueError(f"track {track.id} is locked")
                by_track.setdefault(track.id, []).append(clip)
            deleted: list[str] = []
            for track_id, clips in by_track.items():
                track = self.project.track_by_id(track_id)
                for clip in sorted(clips, key=lambda c: c.start, reverse=True):
                    gap = clip.timeline_duration_frames
                    cut_start = clip.start
                    deleted_id = clip.id
                    track.clips.remove(clip)
                    for c in track.clips_in_order():
                        if c.start >= cut_start:
                            c.start = max(0, c.start - gap)
                    ordered = track.clips_in_order()
                    if ordered and ordered[0].transition_in is not None:
                        ordered[0].transition_in = None
                    deleted.append(deleted_id)
            return {"deleted": deleted, "ripple": True, "count": len(deleted)}

    def move_clip(
        self,
        clip_id: str,
        new_start: int,
        *,
        follow_links: bool = False,
    ) -> Clip | dict[str, Any]:
        """Move clip to new_start. follow_links moves whole link_group by delta."""
        self._assert_clip_track_unlocked(clip_id)
        if new_start < 0:
            raise ValueError(f"new_start must be >= 0, got {new_start}")
        if not follow_links:
            with self._mutate():
                clip = self._find_clip(clip_id)
                clip.start = int(new_start)
                return clip
        clip0 = self._find_clip(clip_id)
        delta = int(new_start) - clip0.start
        return self.nudge_clips([clip_id], delta, follow_links=True)

    def move_to_track(
        self,
        clip_id: str,
        track_id: str,
        *,
        start: int | None = None,
    ) -> dict[str, Any]:
        """Reparent a clip onto another track of the same kind.

        start=None keeps the current timeline start. One undo step.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            src_track, clip = self._find_clip_and_track(clip_id)
            dest = self.project.track_by_id(track_id)
            if dest.locked:
                raise ValueError(f"track {track_id} is locked")
            if dest.kind != src_track.kind:
                raise ValueError(
                    f"cannot move {src_track.kind} clip onto {dest.kind} track"
                )
            if dest.id == src_track.id:
                if start is not None:
                    if int(start) < 0:
                        raise ValueError("start must be >= 0")
                    old_start = clip.start
                    clip.start = int(start)
                    return {
                        "clip_id": clip_id,
                        "from_track_id": src_track.id,
                        "to_track_id": dest.id,
                        "start": {"from": old_start, "to": clip.start},
                        "same_track": True,
                    }
                return {
                    "clip_id": clip_id,
                    "from_track_id": src_track.id,
                    "to_track_id": dest.id,
                    "start": {"from": clip.start, "to": clip.start},
                    "same_track": True,
                    "unchanged": True,
                }
            old_start = clip.start
            new_start = old_start if start is None else int(start)
            if new_start < 0:
                raise ValueError("start must be >= 0")
            src_track.clips.remove(clip)
            clip.start = new_start
            dest.clips.append(clip)
            return {
                "clip_id": clip_id,
                "from_track_id": src_track.id,
                "to_track_id": dest.id,
                "start": {"from": old_start, "to": clip.start},
                "same_track": False,
                "agent_note": "Clip reparented; check overlaps on freeform tracks.",
            }

    def align_clips(
        self,
        clip_ids: list[str],
        *,
        to_frame: int = 0,
        mode: str = "relative",
    ) -> dict[str, Any]:
        """Align many clips' starts.

        mode:
          - relative: shift group so earliest start becomes to_frame
          - start: set every clip's start to to_frame (stack)
        """
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        if mode not in ("relative", "start"):
            raise ValueError("mode must be relative|start")
        if not isinstance(to_frame, int) or to_frame < 0:
            raise ValueError("to_frame must be >= 0")
        ids = list(dict.fromkeys(clip_ids))
        with self._mutate():
            clips: list[tuple[Any, Any]] = []
            for cid in ids:
                track, clip = self._find_clip_and_track(cid)
                if track.locked:
                    raise ValueError(f"track {track.id} is locked")
                clips.append((track, clip))
            moved: list[dict[str, Any]] = []
            if mode == "start":
                for track, clip in clips:
                    old = clip.start
                    clip.start = int(to_frame)
                    moved.append({
                        "clip_id": clip.id,
                        "track_id": track.id,
                        "from": old,
                        "to": clip.start,
                    })
            else:
                min_start = min(c.start for _, c in clips)
                delta = int(to_frame) - min_start
                for track, clip in clips:
                    old = clip.start
                    clip.start = max(0, old + delta)
                    moved.append({
                        "clip_id": clip.id,
                        "track_id": track.id,
                        "from": old,
                        "to": clip.start,
                    })
            return {
                "mode": mode,
                "to_frame": to_frame,
                "moved": moved,
                "count": len(moved),
            }

    def copy_effects(self, clip_id: str) -> dict[str, Any]:
        """Copy clip effects list into session effects clipboard."""
        clip = self._find_clip(clip_id)
        self._effects_clipboard = [dict(e) for e in (clip.effects or [])]
        return {
            "copied": True,
            "clip_id": clip_id,
            "count": len(self._effects_clipboard),
            "types": [e.get("type") for e in self._effects_clipboard],
            "agent_note": "Session effects clipboard — paste_effects. Not in .opm.",
        }

    def paste_effects(
        self,
        clip_id: str,
        *,
        replace: bool = True,
    ) -> dict[str, Any]:
        """Paste effects clipboard onto a clip.

        replace=True: overwrite effects list. replace=False: append.
        """
        if not self._effects_clipboard:
            raise ValueError("effects clipboard empty — copy_effects first")
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            incoming = [dict(e) for e in self._effects_clipboard]
            # Validate each via apply_effect rules by temporarily checking types
            for e in incoming:
                etype = e.get("type")
                if etype not in KNOWN_EFFECT_TYPES:
                    raise ValueError(
                        f"unknown effect type {etype!r} on effects clipboard"
                    )
            old_count = len(clip.effects or [])
            if replace:
                clip.effects = incoming
            else:
                clip.effects = list(clip.effects or []) + incoming
            return {
                "clip_id": clip_id,
                "replace": replace,
                "from_count": old_count,
                "to_count": len(clip.effects or []),
                "types": [e.get("type") for e in (clip.effects or [])],
            }

    def trim_clip(self, clip_id: str, src_in: int, src_out: int) -> Clip:
        with self._mutate():
            clip = self._find_clip(clip_id)
            if src_out <= src_in:
                raise ValueError(f"src_out ({src_out}) must be > src_in ({src_in})")
            media = self.project.media_by_id(clip.media)
            if media.duration_frames and src_out > media.duration_frames:
                raise ValueError(
                    f"src_out ({src_out}) exceeds media duration "
                    f"({media.duration_frames}) of {media.id}"
                )
            clip.src_in = src_in
            clip.src_out = src_out
            return clip

    def set_clip_layout(
        self,
        clip_id: str,
        *,
        start: int | None = None,
        src_in: int | None = None,
        src_out: int | None = None,
    ) -> dict[str, Any]:
        """Atomic layout write for UI drag (move + trim in one undo step).

        Pass any subset of start / src_in / src_out. Validates media bounds and
        non-empty range. Does not auto-ripple neighbors — use ripple_trim for that.
        """
        if start is None and src_in is None and src_out is None:
            raise ValueError("provide start and/or src_in and/or src_out")
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            if clip.speed != 1.0 and (src_in is not None or src_out is not None):
                raise ValueError("set_clip_layout trim requires speed=1.0")
            media = self.project.media_by_id(clip.media)
            old = {
                "start": clip.start,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
            }
            new_start = old["start"] if start is None else int(start)
            new_in = old["src_in"] if src_in is None else int(src_in)
            new_out = old["src_out"] if src_out is None else int(src_out)
            if new_start < 0:
                raise ValueError(f"start must be >= 0, got {new_start}")
            if new_out <= new_in:
                raise ValueError(f"src_out ({new_out}) must be > src_in ({new_in})")
            if new_in < 0:
                raise ValueError("src_in must be >= 0")
            if media.duration_frames and new_out > media.duration_frames:
                raise ValueError(
                    f"src_out ({new_out}) exceeds media duration "
                    f"({media.duration_frames})"
                )
            clip.start = new_start
            clip.src_in = new_in
            clip.src_out = new_out
            return {
                "clip_id": clip.id,
                "from": old,
                "to": {
                    "start": clip.start,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "end": clip.end,
                    "duration_frames": clip.timeline_duration_frames,
                },
                "agent_note": "Layout applied in one undo step; refresh_preview_proxy if scrubbing.",
            }

    def edge_trim(
        self,
        clip_id: str,
        edge: str,
        delta_frames: int,
        *,
        mode: str = "normal",
    ) -> dict[str, Any]:
        """Trim one edge by delta frames.

        edge: ``left`` | ``right``.
        mode ``normal``: left edge moves start+src_in together (right edge fixed
        on timeline); right edge only changes src_out.
        mode ``ripple``: delegates to ripple_trim (followers close the hole).
        Positive delta: left edge → later (shorter head); right edge → later
        (longer tail).
        """
        if edge not in ("left", "right"):
            raise ValueError("edge must be 'left' or 'right'")
        if mode not in ("normal", "ripple"):
            raise ValueError("mode must be 'normal' or 'ripple'")
        if not isinstance(delta_frames, int):
            raise ValueError("delta_frames must be an int")
        if delta_frames == 0:
            clip = self._find_clip(clip_id)
            return {
                "clip_id": clip_id,
                "edge": edge,
                "delta_frames": 0,
                "unchanged": True,
                "to": {
                    "start": clip.start,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                },
            }

        clip = self._find_clip(clip_id)
        if mode == "ripple":
            if edge == "left":
                return {
                    **self.ripple_trim(
                        clip_id, new_src_in=clip.src_in + delta_frames,
                    ),
                    "edge": edge,
                    "mode": mode,
                    "delta_frames": delta_frames,
                }
            return {
                **self.ripple_trim(
                    clip_id, new_src_out=clip.src_out + delta_frames,
                ),
                "edge": edge,
                "mode": mode,
                "delta_frames": delta_frames,
            }

        if edge == "left":
            # Keep right edge fixed on the timeline.
            new_in = clip.src_in + delta_frames
            new_start = clip.start + delta_frames
            if new_start < 0:
                # clamp
                shift = -new_start
                new_start = 0
                new_in += shift
            return {
                **self.set_clip_layout(
                    clip_id, start=new_start, src_in=new_in, src_out=clip.src_out,
                ),
                "edge": edge,
                "mode": mode,
                "delta_frames": delta_frames,
            }
        return {
            **self.set_clip_layout(
                clip_id,
                start=clip.start,
                src_in=clip.src_in,
                src_out=clip.src_out + delta_frames,
            ),
            "edge": edge,
            "mode": mode,
            "delta_frames": delta_frames,
        }

    def split_clip(
        self,
        clip_id: str,
        at_frame: int,
        *,
        follow_links: bool = False,
    ) -> tuple[Clip, Clip] | dict[str, Any]:
        """Split at absolute timeline frame.

        follow_links=True: also split every linked peer that contains the frame;
        left pieces keep the old link_group, right pieces get a new group.
        Returns (left, right) when follow_links=False; else a summary dict.
        """
        if not follow_links:
            with self._mutate():
                return self._split_clip_unlocked(clip_id, at_frame)

        # Collect peers in link group that contain at_frame
        primary = self._find_clip(clip_id)
        candidates = [clip_id]
        if primary.link_group:
            for track in self.project.tracks:
                for c in track.clips:
                    if c.link_group == primary.link_group and c.id not in candidates:
                        candidates.append(c.id)

        with self._mutate():
            splits: list[dict[str, Any]] = []
            rights: list[Clip] = []
            left_group = primary.link_group
            for cid in candidates:
                track, clip = self._find_clip_and_track(cid)
                if not (clip.start < at_frame < clip.end):
                    continue
                if track.locked:
                    raise ValueError(f"track {track.id} is locked")
                left, right = self._split_clip_unlocked(cid, at_frame)
                splits.append({
                    "left_id": left.id,
                    "right_id": right.id,
                    "track_id": track.id,
                })
                rights.append(right)
            if not splits:
                raise ValueError(
                    f"no linked clip contains frame {at_frame} "
                    f"(start from {clip_id})"
                )
            right_group = None
            if left_group and len(rights) >= 1:
                right_group = new_id("lnk")
                for r in rights:
                    r.link_group = right_group
            return {
                "at_frame": at_frame,
                "follow_links": True,
                "splits": splits,
                "count": len(splits),
                "left_link_group": left_group,
                "right_link_group": right_group,
            }

    def _split_clip_unlocked(self, clip_id: str, at_frame: int) -> tuple[Clip, Clip]:
        track, clip = self._find_clip_and_track(clip_id)
        if not (clip.start < at_frame < clip.end):
            raise ValueError(
                f"split point {at_frame} must be strictly inside clip "
                f"{clip_id} ({clip.start}..{clip.end})"
            )
        # Map timeline → source accounting for speed
        local = at_frame - clip.start
        if clip.speed != 1.0:
            split_src = clip.src_in + int(round(local * clip.speed))
        else:
            split_src = clip.src_in + local
        split_src = min(max(split_src, clip.src_in + 1), clip.src_out - 1)
        original_out = clip.src_out
        clip.src_out = split_src
        second = Clip(
            id=new_id("clp"),
            media=clip.media,
            start=at_frame,
            src_in=split_src,
            src_out=original_out,
            speed=clip.speed,
            effects=list(clip.effects or []),
            position=dict(clip.position) if clip.position else None,
            muted=bool(clip.muted),
            name=clip.name,
            color=clip.color,
            link_group=clip.link_group,
        )
        track.clips.append(second)
        return clip, second

    def offset_linked(
        self,
        clip_id: str,
        delta_frames: int,
        *,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        """Nudge peers in the same link_group by delta (default: audio only).

        Used for J/L cuts: keep picture fixed, slide linked sound.
        kinds=None → all peers except the primary clip; pass [\"audio\"] etc.
        """
        if not isinstance(delta_frames, int) or delta_frames == 0:
            raise ValueError("delta_frames must be a non-zero int")
        clip = self._find_clip(clip_id)
        if not clip.link_group:
            raise ValueError(f"clip {clip_id} has no link_group — link or detach_audio first")
        kind_filter = set(kinds) if kinds is not None else None
        with self._mutate():
            moved: list[dict[str, Any]] = []
            for track in self.project.tracks:
                if track.locked:
                    continue
                if kind_filter is not None and track.kind not in kind_filter:
                    continue
                for c in track.clips:
                    if c.link_group != clip.link_group:
                        continue
                    if c.id == clip_id:
                        continue
                    old = c.start
                    c.start = max(0, old + delta_frames)
                    moved.append({
                        "clip_id": c.id,
                        "track_id": track.id,
                        "track_kind": track.kind,
                        "from": old,
                        "to": c.start,
                    })
            if not moved:
                raise ValueError("no linked peers matched kinds filter")
            return {
                "anchor_clip_id": clip_id,
                "link_group": clip.link_group,
                "delta_frames": delta_frames,
                "moved": moved,
                "count": len(moved),
            }

    def j_cut(self, video_clip_id: str, lead_frames: int) -> dict[str, Any]:
        """J-cut: linked audio leads picture by lead_frames (audio starts earlier)."""
        if not isinstance(lead_frames, int) or lead_frames <= 0:
            raise ValueError("lead_frames must be a positive int")
        track, clip = self._find_clip_and_track(video_clip_id)
        if track.kind != "video":
            raise ValueError("j_cut expects a video clip anchor")
        r = self.offset_linked(video_clip_id, -lead_frames, kinds=["audio"])
        return {**r, "cut": "j", "lead_frames": lead_frames}

    def l_cut(self, video_clip_id: str, lag_frames: int) -> dict[str, Any]:
        """L-cut: linked audio lags picture by lag_frames (audio starts later)."""
        if not isinstance(lag_frames, int) or lag_frames <= 0:
            raise ValueError("lag_frames must be a positive int")
        track, clip = self._find_clip_and_track(video_clip_id)
        if track.kind != "video":
            raise ValueError("l_cut expects a video clip anchor")
        r = self.offset_linked(video_clip_id, lag_frames, kinds=["audio"])
        return {**r, "cut": "l", "lag_frames": lag_frames}

    def duplicate_track(
        self,
        track_id: str,
        *,
        copy_clips: bool = True,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Duplicate a track (and optionally all its clips with new ids)."""
        with self._mutate():
            src = self.project.track_by_id(track_id)
            new_tr = self.project.add_track(src.kind)  # type: ignore[arg-type]
            # insert after source for z-order locality
            tracks = self.project.tracks
            tracks.remove(new_tr)
            idx = next(i for i, t in enumerate(tracks) if t.id == track_id)
            tracks.insert(idx + 1, new_tr)
            new_tr.muted = src.muted
            new_tr.solo = False
            new_tr.locked = False
            new_tr.name = name if name is not None else (
                (src.name + " copy") if src.name else None
            )
            # don't copy duck (would double sidechain)
            mapped: list[dict[str, str]] = []
            if copy_clips:
                for c in src.clips_in_order():
                    nc = self.project.add_clip(
                        new_tr,
                        self.project.media_by_id(c.media),
                        c.start,
                        c.src_in,
                        c.src_out,
                    )
                    nc.speed = c.speed
                    nc.effects = [dict(e) for e in (c.effects or [])]
                    if c.position:
                        nc.position = dict(c.position)
                    nc.muted = c.muted
                    nc.name = c.name
                    nc.color = c.color
                    # do not copy link_group (avoid cross-track A/V confusion)
                    if c.transition_in:
                        nc.transition_in = dict(c.transition_in)
                    mapped.append({"from": c.id, "to": nc.id})
            return {
                "track_id": new_tr.id,
                "from_track_id": track_id,
                "kind": new_tr.kind,
                "name": new_tr.name,
                "clips": mapped,
                "clip_count": len(mapped),
                "index": idx + 1,
            }

    def list_unused_media(self) -> dict[str, Any]:
        """Media assets not referenced by any clip."""
        used = {
            c.media
            for t in self.project.tracks
            for c in t.clips
        }
        unused = [
            {
                "media_id": m.id,
                "path": m.path,
                "kind": m.kind,
                "duration_frames": m.duration_frames,
            }
            for m in self.project.media
            if m.id not in used
        ]
        return {"count": len(unused), "media": unused}

    def purge_unused_media(self, *, delete_files: bool = False) -> dict[str, Any]:
        """Remove unused media entries from the project.

        delete_files=True also deletes files under bundle media/ (irreversible).
        """
        unused = self.list_unused_media()["media"]
        if not unused:
            return {"removed": [], "count": 0, "files_deleted": []}
        with self._mutate():
            ids = {u["media_id"] for u in unused}
            removed: list[str] = []
            files_deleted: list[str] = []
            keep: list = []
            for m in self.project.media:
                if m.id not in ids:
                    keep.append(m)
                    continue
                removed.append(m.id)
                if delete_files:
                    try:
                        p = self.bundle.media_path(m.path)
                        if p.exists() and p.is_file():
                            p.unlink()
                            files_deleted.append(str(p))
                    except OSError:
                        pass
            self.project.media = keep
            return {
                "removed": removed,
                "count": len(removed),
                "files_deleted": files_deleted,
                "delete_files": delete_files,
            }

    def project_stats(self) -> dict[str, Any]:
        """Quick project census for agents/UI status bars."""
        tracks = self.project.tracks
        clips = [c for t in tracks for c in t.clips]
        groups = {c.link_group for c in clips if c.link_group}
        return {
            "project_id": self.project.id,
            "fps": self.project.timebase.fps,
            "resolution": {
                "w": self.project.resolution.w,
                "h": self.project.resolution.h,
            },
            "duration_frames": self.project.duration_frames(),
            "duration_seconds": round(
                self.project.duration_frames()
                / float(self.project.timebase.fps or 30.0),
                3,
            ),
            "track_count": len(tracks),
            "clip_count": len(clips),
            "media_count": len(self.project.media),
            "unused_media_count": self.list_unused_media()["count"],
            "marker_count": len(self.project.markers),
            "link_group_count": len(groups),
            "dirty": bool(getattr(self, "_dirty", False)),
            "undo_depth": len(self._undo_stack),
            "has_clipboard": bool(self._clipboard),
        }

    def split_all_at(
        self,
        at_frame: int,
        *,
        track_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Razor: split every clip that contains ``at_frame`` (one undo step).

        track_ids=None → all tracks. Skips clips that don't contain the frame.
        """
        if not isinstance(at_frame, int):
            raise ValueError("at_frame must be an int")
        with self._mutate():
            tracks = self.project.tracks
            if track_ids is not None:
                wanted = set(track_ids)
                tracks = [t for t in tracks if t.id in wanted]
            splits: list[dict[str, str]] = []
            # collect ids first (mutating while iterating clips is unsafe)
            targets: list[str] = []
            for track in tracks:
                for clip in list(track.clips):
                    if clip.start < at_frame < clip.end:
                        targets.append(clip.id)
            for cid in targets:
                left, right = self._split_clip_unlocked(cid, at_frame)
                splits.append({
                    "left_id": left.id,
                    "right_id": right.id,
                    "track_id": self._find_clip_and_track(left.id)[0].id,
                })
            return {
                "at_frame": at_frame,
                "split_count": len(splits),
                "splits": splits,
                "agent_note": "Razor cut across tracks; empty if playhead not inside any clip.",
            }

    def link_transition(
        self,
        right_clip_id: str,
        *,
        transition_type: str = "cross_dissolve",
        duration_frames: int = 12,
        left_clip_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a transition into ``right_clip_id`` from its previous hard-cut neighbor.

        Optional left_clip_id validates adjacency. Same rules as add_transition.
        """
        track, right = self._find_clip_and_track(right_clip_id)
        ordered = track.clips_in_order()
        idx = ordered.index(right)
        if idx == 0:
            raise ValueError("right clip is first — nothing to dissolve from")
        left = ordered[idx - 1]
        if left_clip_id is not None and left.id != left_clip_id:
            raise ValueError(
                f"expected left neighbor {left_clip_id}, found {left.id}"
            )
        clip = self.add_transition(right_clip_id, transition_type, duration_frames)
        return {
            "left_clip_id": left.id,
            "right_clip_id": clip.id,
            "transition": dict(clip.transition_in or {}),
            "agent_note": "Timeline shortened by duration_frames (overlap).",
        }

    def snap_points(self, *, include_markers: bool = True) -> dict[str, Any]:
        """Frame positions useful for UI snap (clip edges + markers + 0)."""
        points: set[int] = {0}
        for track in self.project.tracks:
            for clip in track.clips:
                points.add(int(clip.start))
                points.add(int(clip.end))
        if include_markers:
            for m in self.project.markers:
                points.add(int(m.frame))
        ordered = sorted(p for p in points if p >= 0)
        return {
            "frames": ordered,
            "count": len(ordered),
            "agent_note": "Snap drag/trim targets within a few frames of these.",
        }

    def copy_clip(self, clip_id: str) -> dict[str, Any]:
        """Copy clip blueprint into session clipboard (media + source range + effects)."""
        track, clip = self._find_clip_and_track(clip_id)
        self._clipboard = {
            "media": clip.media,
            "src_in": clip.src_in,
            "src_out": clip.src_out,
            "speed": clip.speed,
            "effects": [dict(e) for e in (clip.effects or [])],
            "position": dict(clip.position) if clip.position else None,
            "name": clip.name,
            "color": clip.color,
            "source_track_kind": track.kind,
            "source_clip_id": clip.id,
            "duration_frames": clip.timeline_duration_frames,
        }
        return {
            "copied": True,
            "clip_id": clip_id,
            "media_id": clip.media,
            "duration_frames": clip.timeline_duration_frames,
            "agent_note": "Session clipboard — paste_clip / duplicate_clip. Not saved in .opm.",
        }

    def paste_clip(
        self,
        *,
        track_id: str | None = None,
        start: int | None = None,
        at_playhead: bool = False,
        playhead_frame: int | None = None,
        mode: str = "insert",
    ) -> dict[str, Any]:
        """Paste clipboard as a new clip. start=None → end of target track.

        mode:
          - insert (default): place without removing what is already there
            (may overlap freeform tracks; base contiguity is caller's problem).
          - overwrite: lift [place, place+duration) on the target track first
            (no ripple), then place — classic NLE overwrite edit.
        """
        if not self._clipboard:
            raise ValueError("clipboard empty — copy_clip first")
        if mode not in ("insert", "overwrite"):
            raise ValueError("mode must be 'insert' or 'overwrite'")
        bp = self._clipboard
        media = self.project.media_by_id(bp["media"])
        kind = bp.get("source_track_kind") or "video"
        tid = track_id
        if tid is None:
            tracks = [t for t in self.project.tracks if t.kind == kind]
            if not tracks:
                tid = self.add_track(kind).id  # type: ignore[arg-type]
            else:
                tid = tracks[0].id
        track = self.project.track_by_id(tid)
        if start is not None:
            place_at = int(start)
        elif at_playhead and playhead_frame is not None:
            place_at = max(0, int(playhead_frame))
        else:
            ordered = track.clips_in_order()
            place_at = ordered[-1].end if ordered else 0

        # Timeline footprint of the paste (respect clipboard speed)
        src_len = int(bp["src_out"]) - int(bp["src_in"])
        speed = float(bp.get("speed") or 1.0) or 1.0
        paste_dur = max(1, round(src_len / speed))

        with self._mutate():
            track = self.project.track_by_id(tid)
            if track.locked:
                raise ValueError(f"track {tid} is locked")
            extracted = None
            if mode == "overwrite":
                extracted = self._extract_time_unlocked(
                    tid, place_at, place_at + paste_dur, ripple=False,
                )
            media = self.project.media_by_id(bp["media"])
            clip = self.project.add_clip(
                track, media, place_at, int(bp["src_in"]), int(bp["src_out"]),
            )
            clip.speed = speed
            clip.effects = [dict(e) for e in (bp.get("effects") or [])]
            if bp.get("position"):
                clip.position = dict(bp["position"])
            if bp.get("name"):
                clip.name = bp["name"]
            if bp.get("color"):
                clip.color = bp["color"]
            return {
                "clip_id": clip.id,
                "track_id": tid,
                "start": clip.start,
                "end": clip.end,
                "mode": mode,
                "from_clipboard": bp.get("source_clip_id"),
                "overwrite_extract": extracted,
            }

    def duplicate_clip(
        self,
        clip_id: str,
        *,
        offset_frames: int | None = None,
    ) -> dict[str, Any]:
        """Copy then paste immediately after the original (or +offset)."""
        self.copy_clip(clip_id)
        track, clip = self._find_clip_and_track(clip_id)
        start = clip.end if offset_frames is None else clip.start + int(offset_frames)
        return self.paste_clip(track_id=track.id, start=start)

    def set_in_point(self, frame: int | None = None, *, time_seconds: float | None = None) -> dict[str, Any]:
        fps = float(self.project.timebase.fps or 30.0)
        if frame is None:
            if time_seconds is None:
                raise ValueError("provide frame or time_seconds")
            frame = int(round(float(time_seconds) * fps))
        if frame < 0:
            raise ValueError("in point must be >= 0")
        self._in_point = int(frame)
        if self._out_point is not None and self._out_point <= self._in_point:
            self._out_point = None
        return self.get_in_out()

    def set_out_point(self, frame: int | None = None, *, time_seconds: float | None = None) -> dict[str, Any]:
        fps = float(self.project.timebase.fps or 30.0)
        if frame is None:
            if time_seconds is None:
                raise ValueError("provide frame or time_seconds")
            frame = int(round(float(time_seconds) * fps))
        if frame < 0:
            raise ValueError("out point must be >= 0")
        if self._in_point is not None and frame <= self._in_point:
            raise ValueError("out point must be > in point")
        self._out_point = int(frame)
        return self.get_in_out()

    def clear_in_out(self) -> dict[str, Any]:
        self._in_point = None
        self._out_point = None
        return self.get_in_out()

    def get_in_out(self) -> dict[str, Any]:
        fps = float(self.project.timebase.fps or 30.0)
        inn = self._in_point
        out = self._out_point
        return {
            "in_frame": inn,
            "out_frame": out,
            "in_seconds": None if inn is None else round(inn / fps, 3),
            "out_seconds": None if out is None else round(out / fps, 3),
            "duration_frames": (
                None if inn is None or out is None else max(0, out - inn)
            ),
            "ready": inn is not None and out is not None and out > inn,
        }

    def export_work_area(
        self,
        output_path: str | Path,
        *,
        normalize_preset: str | None = "streaming",
        run_delivery_check: bool = True,
        delivery_preset: str = "streaming",
    ) -> dict[str, Any]:
        """Export [in, out) work area. Requires set_in_point + set_out_point."""
        io = self.get_in_out()
        if not io["ready"]:
            raise ValueError("set in and out points first (set_in_point / set_out_point)")
        fps = float(self.project.timebase.fps or 30.0)
        start_s = io["in_frame"] / fps
        end_s = io["out_frame"] / fps
        return self.export_range(
            output_path,
            start_s,
            end_s,
            normalize_preset=normalize_preset,
            run_delivery_check=run_delivery_check,
            delivery_preset=delivery_preset,
        )

    def delete_clip(self, clip_id: str) -> Clip:
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            track.clips.remove(clip)
            return clip

    def ripple_delete(self, clip_id: str) -> dict[str, Any]:
        """Delete a clip and pull later clips on the same track left to close the hole.

        Also clears ``transition_in`` on the clip that becomes adjacent when that
        transition no longer makes sense (first clip after ripple has no prev).
        Returns deleted clip id, frames closed, and shifted clip ids.
        """
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            gap = clip.timeline_duration_frames
            # Account for transition overlap into this clip
            if clip.transition_in:
                gap = max(0, gap)  # start already overlapped; footprint still timeline_duration
            cut_start = clip.start
            deleted_id = clip.id
            track.clips.remove(clip)
            shifted: list[str] = []
            for c in track.clips_in_order():
                if c.start >= cut_start:
                    c.start = max(0, c.start - gap)
                    shifted.append(c.id)
            # First remaining clip on track should not keep transition_in
            ordered = track.clips_in_order()
            if ordered and ordered[0].transition_in is not None:
                # restore start if transition had pulled it left (we already
                # only shifted by timeline duration; clear transition flag)
                ordered[0].transition_in = None
            # Re-pack hard cuts if we created accidental overlaps from transitions
            return {
                "deleted_id": deleted_id,
                "track_id": track.id,
                "frames_closed": gap,
                "shifted": shifted,
            }

    def slip_clip(self, clip_id: str, delta_src_frames: int) -> dict[str, Any]:
        """Slip: slide source in/out together; timeline start/duration unchanged.

        Positive delta uses later source material (window moves forward in the
        file). Clamped to media bounds. speed must be 1.0 for now.
        """
        with self._mutate():
            clip = self._find_clip(clip_id)
            if clip.speed != 1.0:
                raise ValueError("slip_clip requires speed=1.0 for now")
            if not isinstance(delta_src_frames, int):
                raise ValueError("delta_src_frames must be an int")
            media = self.project.media_by_id(clip.media)
            dur = clip.src_out - clip.src_in
            if dur <= 0:
                raise ValueError("clip has empty source range")
            new_in = clip.src_in + delta_src_frames
            new_out = clip.src_out + delta_src_frames
            if media.duration_frames:
                # clamp window inside media
                if new_in < 0:
                    new_out -= new_in
                    new_in = 0
                if new_out > media.duration_frames:
                    shift = new_out - media.duration_frames
                    new_in -= shift
                    new_out = media.duration_frames
                if new_in < 0 or new_out - new_in != dur:
                    raise ValueError(
                        f"slip by {delta_src_frames} does not fit media "
                        f"(duration_frames={media.duration_frames}, "
                        f"window={dur})"
                    )
            else:
                if new_in < 0:
                    raise ValueError("slip would push src_in below 0")
            old_in, old_out = clip.src_in, clip.src_out
            clip.src_in = new_in
            clip.src_out = new_out
            return {
                "clip_id": clip.id,
                "src_in": {"from": old_in, "to": new_in},
                "src_out": {"from": old_out, "to": new_out},
                "timeline_start": clip.start,
                "timeline_duration": clip.timeline_duration_frames,
                "agent_note": "Timeline footprint unchanged; only source window moved.",
            }

    def roll_edit(
        self,
        left_clip_id: str,
        right_clip_id: str,
        delta_frames: int,
    ) -> dict[str, Any]:
        """Roll: move the edit point between two adjacent hard-cut clips.

        Positive delta shortens left / lengthens right (cut moves later).
        Both clips must be on the same track, hard-cut adjacent (no gap,
        right has no transition_in), speed=1.0.
        """
        with self._mutate():
            if not isinstance(delta_frames, int) or delta_frames == 0:
                raise ValueError("delta_frames must be a non-zero int")
            lt, left = self._find_clip_and_track(left_clip_id)
            rt, right = self._find_clip_and_track(right_clip_id)
            if lt.id != rt.id:
                raise ValueError("roll_edit requires both clips on the same track")
            if left.speed != 1.0 or right.speed != 1.0:
                raise ValueError("roll_edit requires speed=1.0 on both clips")
            if right.transition_in is not None:
                raise ValueError(
                    "roll_edit needs a hard cut — remove transition_in on the right clip first"
                )
            if right.start != left.end:
                raise ValueError(
                    f"clips not adjacent hard-cut: left ends {left.end}, "
                    f"right starts {right.start}"
                )
            # Positive: left grows on timeline → left.src_out += d, right.start += d, right.src_in += d
            # Negative: opposite
            new_left_out = left.src_out + delta_frames
            new_right_in = right.src_in + delta_frames
            new_right_start = right.start + delta_frames
            if new_left_out <= left.src_in:
                raise ValueError("roll would empty the left clip")
            if right.src_out <= new_right_in:
                raise ValueError("roll would empty the right clip")
            lmedia = self.project.media_by_id(left.media)
            rmedia = self.project.media_by_id(right.media)
            if lmedia.duration_frames and new_left_out > lmedia.duration_frames:
                raise ValueError("roll exceeds left media duration")
            if new_right_in < 0:
                raise ValueError("roll pushes right src_in below 0")
            if rmedia.duration_frames and right.src_out > rmedia.duration_frames:
                pass  # already valid
            old = {
                "left_out": left.src_out,
                "right_in": right.src_in,
                "right_start": right.start,
            }
            left.src_out = new_left_out
            right.src_in = new_right_in
            right.start = new_right_start
            # still adjacent
            if right.start != left.end:
                raise RuntimeError("internal: roll broke adjacency")
            return {
                "left_clip_id": left.id,
                "right_clip_id": right.id,
                "delta_frames": delta_frames,
                "left_src_out": {"from": old["left_out"], "to": left.src_out},
                "right_src_in": {"from": old["right_in"], "to": right.src_in},
                "right_start": {"from": old["right_start"], "to": right.start},
                "edit_frame": left.end,
                "agent_note": "Cut point rolled; total timeline length of the pair unchanged.",
            }

    def slide_clip(self, clip_id: str, delta_frames: int) -> dict[str, Any]:
        """Slide: move a middle clip; neighbors absorb so sequence length holds.

        Requires previous and next hard-cut neighbors on the same track,
        speed=1.0, no transition_in on self or next. Positive = later on timeline.
        """
        with self._mutate():
            if not isinstance(delta_frames, int) or delta_frames == 0:
                raise ValueError("delta_frames must be a non-zero int")
            track, clip = self._find_clip_and_track(clip_id)
            if clip.speed != 1.0:
                raise ValueError("slide_clip requires speed=1.0")
            if clip.transition_in is not None:
                raise ValueError("slide_clip needs hard cuts — remove transition_in first")
            ordered = track.clips_in_order()
            idx = ordered.index(clip)
            if idx == 0 or idx == len(ordered) - 1:
                raise ValueError("slide_clip needs both a previous and next neighbor")
            prev, nxt = ordered[idx - 1], ordered[idx + 1]
            if prev.speed != 1.0 or nxt.speed != 1.0:
                raise ValueError("slide_clip requires speed=1.0 on neighbors")
            if nxt.transition_in is not None:
                raise ValueError("next clip has transition_in — remove it first")
            if clip.start != prev.end or nxt.start != clip.end:
                raise ValueError("slide_clip requires contiguous hard-cut neighbors")
            # +d: prev longer, clip later, next loses head
            new_prev_out = prev.src_out + delta_frames
            new_clip_start = clip.start + delta_frames
            new_next_in = nxt.src_in + delta_frames
            new_next_start = nxt.start + delta_frames
            if new_prev_out <= prev.src_in:
                raise ValueError("slide would empty the previous clip")
            if nxt.src_out <= new_next_in:
                raise ValueError("slide would empty the next clip")
            pmedia = self.project.media_by_id(prev.media)
            nmedia = self.project.media_by_id(nxt.media)
            if pmedia.duration_frames and new_prev_out > pmedia.duration_frames:
                raise ValueError("slide exceeds previous media duration")
            if new_next_in < 0:
                raise ValueError("slide pushes next src_in below 0")
            if nmedia.duration_frames and nxt.src_out > nmedia.duration_frames:
                pass
            old = {
                "prev_out": prev.src_out,
                "clip_start": clip.start,
                "next_in": nxt.src_in,
                "next_start": nxt.start,
            }
            prev.src_out = new_prev_out
            clip.start = new_clip_start
            nxt.src_in = new_next_in
            nxt.start = new_next_start
            if clip.start != prev.end or nxt.start != clip.end:
                raise RuntimeError("internal: slide broke contiguity")
            return {
                "clip_id": clip.id,
                "prev_clip_id": prev.id,
                "next_clip_id": nxt.id,
                "delta_frames": delta_frames,
                "prev_src_out": {"from": old["prev_out"], "to": prev.src_out},
                "clip_start": {"from": old["clip_start"], "to": clip.start},
                "next_src_in": {"from": old["next_in"], "to": nxt.src_in},
                "agent_note": "Middle clip slid; A/B/C block length unchanged.",
            }

    def ripple_trim(
        self,
        clip_id: str,
        *,
        new_src_in: int | None = None,
        new_src_out: int | None = None,
    ) -> dict[str, Any]:
        """Trim source range and ripple later clips to close/open the hole.

        Provide new_src_in and/or new_src_out (at least one). speed=1.0 only.
        Trimming the head moves the clip's start earlier/later with ripple of
        following clips; trimming the tail only ripples followers.
        """
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            if clip.speed != 1.0:
                raise ValueError("ripple_trim requires speed=1.0")
            if new_src_in is None and new_src_out is None:
                raise ValueError("provide new_src_in and/or new_src_out")
            media = self.project.media_by_id(clip.media)
            old_in, old_out = clip.src_in, clip.src_out
            old_start = clip.start
            old_dur = clip.timeline_duration_frames
            src_in = old_in if new_src_in is None else int(new_src_in)
            src_out = old_out if new_src_out is None else int(new_src_out)
            if src_out <= src_in:
                raise ValueError("src_out must be > src_in")
            if src_in < 0:
                raise ValueError("src_in must be >= 0")
            if media.duration_frames and src_out > media.duration_frames:
                raise ValueError("src_out exceeds media duration")
            # Head trim: changing src_in by +d shortens clip and shifts content;
            # timeline start stays; duration shrinks by d → ripple followers left by d
            head_delta = src_in - old_in  # + means shorter from head
            tail_delta = old_out - src_out  # + means shorter from tail
            # net duration change
            clip.src_in = src_in
            clip.src_out = src_out
            new_dur = clip.timeline_duration_frames
            delta_dur = old_dur - new_dur  # positive = got shorter
            if delta_dur != 0:
                # shift later clips
                for c in track.clips_in_order():
                    if c.id == clip.id:
                        continue
                    if c.start >= old_start + old_dur:
                        c.start = max(0, c.start - delta_dur)
            return {
                "clip_id": clip.id,
                "src_in": {"from": old_in, "to": src_in},
                "src_out": {"from": old_out, "to": src_out},
                "duration_delta_frames": -delta_dur,
                "timeline_start": clip.start,
                "agent_note": "Trim applied; later clips rippled to keep contiguity.",
            }

    def _collapse_last_undos(self, n: int) -> None:
        """Keep only the earliest of the last n undo snapshots (one-undo batches)."""
        if n <= 1 or len(self._undo_stack) < n:
            return
        del self._undo_stack[-(n - 1) :]

    def trim_to_playhead(
        self,
        clip_id: str,
        playhead_frame: int,
        *,
        edge: str = "head",
        mode: str = "ripple",
        follow_links: bool = False,
    ) -> dict[str, Any]:
        """Trim clip head or tail to an absolute playhead frame (NLE Q/W).

        edge:
          - head (Q): advance src_in to playhead; ripple keeps timeline start,
            normal moves start to playhead (gap may remain to the left).
          - tail (W): cut src_out so clip ends at playhead.

        mode: ripple | normal (see edge_trim / ripple_trim).
        follow_links=True: also trim linked peers that contain the playhead
        (one combined undo).
        speed=1.0 required.
        """
        if edge not in ("head", "tail", "left", "right"):
            raise ValueError("edge must be head|tail (or left|right aliases)")
        if edge == "left":
            edge = "head"
        if edge == "right":
            edge = "tail"
        if mode not in ("ripple", "normal"):
            raise ValueError("mode must be ripple|normal")
        if not isinstance(playhead_frame, int):
            raise ValueError("playhead_frame must be an int")

        ph = int(playhead_frame)
        if follow_links:
            ids = self._expand_link_ids([clip_id])
            results: list[dict[str, Any]] = []
            for cid in ids:
                try:
                    results.append(
                        self.trim_to_playhead(
                            cid, ph, edge=edge, mode=mode, follow_links=False,
                        )
                    )
                except ValueError:
                    continue
            if not results:
                raise ValueError(
                    f"no linked clip contains playhead {ph} (from {clip_id})"
                )
            self._collapse_last_undos(len(results))
            return {
                "follow_links": True,
                "edge": edge,
                "mode": mode,
                "playhead_frame": ph,
                "trimmed": results,
                "count": len(results),
            }

        self._assert_clip_track_unlocked(clip_id)
        track, clip = self._find_clip_and_track(clip_id)
        if clip.speed != 1.0:
            raise ValueError("trim_to_playhead requires speed=1.0")
        if not (clip.start < ph < clip.end):
            raise ValueError(
                f"playhead {ph} must be strictly inside clip "
                f"[{clip.start}, {clip.end})"
            )

        local = ph - clip.start
        src_at = clip.src_in + local
        src_at = min(max(src_at, clip.src_in + 1), clip.src_out - 1)

        if edge == "head":
            if mode == "ripple":
                r = self.ripple_trim(clip_id, new_src_in=src_at)
            else:
                # Right edge fixed on timeline
                r = self.set_clip_layout(
                    clip_id,
                    start=ph,
                    src_in=src_at,
                    src_out=clip.src_out,
                )
            return {
                **r,
                "edge": "head",
                "mode": mode,
                "playhead_frame": ph,
                "agent_note": "Head trimmed to playhead (Q-style).",
            }

        # tail
        if mode == "ripple":
            r = self.ripple_trim(clip_id, new_src_out=src_at)
        else:
            r = self.set_clip_layout(
                clip_id,
                start=clip.start,
                src_in=clip.src_in,
                src_out=src_at,
            )
        return {
            **r,
            "edge": "tail",
            "mode": mode,
            "playhead_frame": ph,
            "agent_note": "Tail trimmed to playhead (W-style).",
        }

    def clear_clip_effects(
        self,
        clip_id: str,
        *,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Remove clip effects. types=None clears all; else only listed types.

        Does not clear speed, position, transition_in, mute, name, color.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            before = list(clip.effects or [])
            if types is None:
                removed = before
                clip.effects = []
            else:
                type_set = set(types)
                removed = [e for e in before if e.get("type") in type_set]
                clip.effects = [e for e in before if e.get("type") not in type_set]
            return {
                "clip_id": clip_id,
                "removed_count": len(removed),
                "removed_types": [e.get("type") for e in removed],
                "remaining_count": len(clip.effects or []),
            }

    def list_clip_effects(self, clip_id: str) -> dict[str, Any]:
        """List effect dicts on a clip (read-only)."""
        clip = self._find_clip(clip_id)
        effects = [dict(e) for e in (clip.effects or [])]
        return {
            "clip_id": clip_id,
            "count": len(effects),
            "effects": effects,
        }

    def ensure_slug_media(self, kind: MediaKind = "video") -> Media:
        """Long black video or silence audio for gap-fill pads (cached in media/)."""
        import subprocess

        fps = float(self.project.timebase.fps or 30.0)
        # ~10 minutes is enough for dogfood/edits; longer gaps re-use via trim
        slug_seconds = 600
        w, h = self.project.resolution.w, self.project.resolution.h
        tag = f"slug_{kind}_{int(fps)}_{w}x{h}" if kind == "video" else f"slug_audio_{self.project.timebase.sample_rate}"
        for m in self.project.media:
            if m.origin and m.origin.get("slug") == tag:
                return m

        self.bundle.media_dir.mkdir(parents=True, exist_ok=True)
        if kind == "video":
            name = f"{tag}.mp4"
            dest = self.bundle.media_dir / name
            if not dest.exists():
                proc = subprocess.run(
                    [
                        "ffmpeg", "-y", "-hide_banner",
                        "-f", "lavfi",
                        "-i", f"color=c=black:size={w}x{h}:duration={slug_seconds}:rate={fps}",
                        "-f", "lavfi",
                        "-i", f"anullsrc=r={self.project.timebase.sample_rate}:cl=stereo",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                        "-c:a", "aac", "-shortest", str(dest),
                    ],
                    capture_output=True, text=True,
                )
                if proc.returncode != 0 or not dest.exists():
                    raise RuntimeError(
                        f"slug video failed:\n{(proc.stderr or '')[-1200:]}"
                    )
            after_dur = self.project.timebase.seconds_to_frames(slug_seconds)
            with self._mutate():
                media = self.project.add_media(
                    kind="video",
                    path=name,
                    duration_frames=after_dur,
                    has_audio=True,
                    origin={"slug": tag, "kind": "black"},
                )
            return media

        if kind != "audio":
            raise ValueError("slug kind must be video or audio")
        name = f"{tag}.m4a"
        dest = self.bundle.media_dir / name
        sr = int(self.project.timebase.sample_rate or 48000)
        if not dest.exists():
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner",
                    "-f", "lavfi",
                    "-i", f"anullsrc=r={sr}:cl=stereo",
                    "-t", str(slug_seconds),
                    "-c:a", "aac", str(dest),
                ],
                capture_output=True, text=True,
            )
            if proc.returncode != 0 or not dest.exists():
                raise RuntimeError(
                    f"slug audio failed:\n{(proc.stderr or '')[-1200:]}"
                )
        after_dur = self.project.timebase.seconds_to_frames(slug_seconds)
        with self._mutate():
            media = self.project.add_media(
                kind="audio",
                path=name,
                duration_frames=after_dur,
                has_audio=True,
                origin={"slug": tag, "kind": "silence"},
            )
        return media

    def fill_track_gaps(
        self,
        track_id: str | None = None,
        *,
        mode: str = "slug",
        from_frame: int = 0,
    ) -> dict[str, Any]:
        """Make a base track exportable after freeform drag.

        mode ``slug``: insert black (video) or silence (audio) pads in gaps,
        and pad head to frame 0 if the first clip starts later.
        mode ``close``: pack left via close_gaps (no pads).
        track_id=None → first video track.
        """
        if mode not in ("slug", "close"):
            raise ValueError("mode must be 'slug' or 'close'")
        if track_id is None:
            vids = [t for t in self.project.tracks if t.kind == "video"]
            if not vids:
                raise ValueError("no video track to fill")
            track_id = vids[0].id
        if mode == "close":
            return {
                "mode": "close",
                **self.close_gaps(track_id, from_frame=from_frame),
            }

        track = self.project.track_by_id(track_id)
        slug_kind: MediaKind = "audio" if track.kind == "audio" else "video"
        # Ensure slug media outside multi-clip mutate first
        slug = self.ensure_slug_media(slug_kind)
        pads: list[dict[str, Any]] = []

        with self._mutate():
            track = self.project.track_by_id(track_id)
            ordered = track.clips_in_order()
            if not ordered:
                return {
                    "mode": "slug",
                    "track_id": track_id,
                    "pads": [],
                    "agent_note": "empty track — nothing to fill",
                }
            gaps: list[tuple[int, int, str]] = []
            if ordered[0].start > 0:
                gaps.append((0, ordered[0].start, "head"))
            for prev, nxt in zip(ordered, ordered[1:]):
                if nxt.transition_in is not None:
                    continue
                if nxt.start > prev.end:
                    gaps.append((prev.end, nxt.start - prev.end, "interior"))
            for start, gap, role in gaps:
                if gap <= 0:
                    continue
                if gap > slug.duration_frames:
                    raise ValueError(
                        f"gap {gap} exceeds slug media {slug.duration_frames}"
                    )
                pad = self.project.add_clip(track, slug, start, 0, gap)
                pads.append({
                    "clip_id": pad.id,
                    "start": start,
                    "end": start + gap,
                    "role": role,
                })

        return {
            "mode": "slug",
            "track_id": track_id,
            "pads": pads,
            "pad_count": len(pads),
            "slug_media_id": slug.id,
            "agent_note": (
                "Black/silence pads keep base track contiguous for export. "
                "Use mode=close to pack instead of padding."
            ),
        }

    def prepare_export(self, *, fill_video: bool = True, fill_audio: bool = False) -> dict[str, Any]:
        """Best-effort make base tracks contiguous before export (slug pads)."""
        results: list[dict[str, Any]] = []
        if fill_video:
            vids = [t for t in self.project.tracks if t.kind == "video"]
            if vids and vids[0].clips:
                try:
                    results.append(self.fill_track_gaps(vids[0].id, mode="slug"))
                except Exception as e:
                    results.append({"track_id": vids[0].id, "error": str(e)[:300]})
        if fill_audio:
            auds = [t for t in self.project.tracks if t.kind == "audio"]
            if auds and auds[0].clips:
                try:
                    results.append(self.fill_track_gaps(auds[0].id, mode="slug"))
                except Exception as e:
                    results.append({"track_id": auds[0].id, "error": str(e)[:300]})
        return {"fills": results}

    def close_gaps(self, track_id: str, *, from_frame: int = 0) -> dict[str, Any]:
        """Pack clips on a track leftward so they are contiguous from from_frame.

        Base video/audio expect contiguity at export; use after lifts/deletes.
        Transitions: cleared (agent re-applies) to avoid overlap math bugs.
        """
        with self._mutate():
            track = self.project.track_by_id(track_id)
            ordered = track.clips_in_order()
            if not ordered:
                return {"track_id": track_id, "moved": [], "cursor": from_frame}
            cursor = int(from_frame)
            moved: list[dict[str, Any]] = []
            for c in ordered:
                if c.start < from_frame:
                    continue
                old = c.start
                if c.transition_in is not None:
                    c.transition_in = None
                c.start = cursor
                if old != cursor:
                    moved.append({"clip_id": c.id, "from": old, "to": cursor})
                cursor = c.end
            return {
                "track_id": track_id,
                "moved": moved,
                "cursor": cursor,
                "agent_note": "Transitions cleared — re-add with place_after/add_transition if needed.",
            }

    def detach_audio(
        self,
        clip_id: str,
        audio_track_id: str | None = None,
        *,
        audio_start_offset_frames: int = 0,
        link: bool = True,
    ) -> dict[str, Any]:
        """Copy a video clip's audio onto an audio track for independent J/L timing.

        Places the same media range on an audio track (creates overlay audio
        track when needed so starts may leave gaps). Once any audio-track clips
        exist, export uses them instead of embedded video audio — so this
        effectively splits picture vs sound. ``audio_start_offset_frames``
        negative = J-cut lead (audio earlier); positive = L-cut lag.

        link=True assigns a shared link_group so nudge/delete can stay in sync.
        """
        with self._mutate():
            vtrack, clip = self._find_clip_and_track(clip_id)
            media = self.project.media_by_id(clip.media)
            if not media.has_audio:
                raise ValueError(
                    f"clip {clip_id} media {media.id} has no audio to detach"
                )
            if vtrack.kind != "video":
                raise ValueError("detach_audio expects a clip on a video track")

            audio_tracks = [t for t in self.project.tracks if t.kind == "audio"]
            if audio_track_id is not None:
                atrack = self.project.track_by_id(audio_track_id)
                if atrack.kind != "audio":
                    raise ValueError(f"{audio_track_id} is not an audio track")
            else:
                # Prefer a non-base (overlay) audio track for free timing
                if not audio_tracks:
                    self.project.add_track("audio")  # possible empty base
                    atrack = self.project.add_track("audio")
                elif len(audio_tracks) == 1:
                    # If only base exists and we need free start, add overlay
                    atrack = self.project.add_track("audio")
                else:
                    atrack = audio_tracks[-1]

            a_start = max(0, clip.start + int(audio_start_offset_frames))
            audio_clip = self.project.add_clip(
                atrack, media, a_start, clip.src_in, clip.src_out,
            )
            if clip.speed != 1.0:
                audio_clip.speed = clip.speed
            link_group = None
            if link:
                link_group = clip.link_group or new_id("lnk")
                clip.link_group = link_group
                audio_clip.link_group = link_group
            return {
                "video_clip_id": clip.id,
                "audio_clip_id": audio_clip.id,
                "audio_track_id": atrack.id,
                "audio_start": a_start,
                "offset_frames": int(audio_start_offset_frames),
                "link_group": link_group,
                "agent_note": (
                    "Picture stays on video; sound is on audio track. "
                    "Negative offset = J-cut (audio leads). Embedded video "
                    "audio is suppressed while any audio-track clips exist."
                    + (" Clips are linked." if link else "")
                ),
            }

    def get_clip_gain_db(self, clip_id: str) -> float:
        """Return the last gain effect dB on the clip, or 0.0 if none."""
        clip = self._find_clip(clip_id)
        db = 0.0
        for fx in clip.effects or []:
            if fx.get("type") == "gain" and isinstance(fx.get("db"), (int, float)):
                db = float(fx["db"])
        return db

    def set_clip_gain(self, clip_id: str, db: float) -> dict[str, Any]:
        """Set clip gain in dB (replaces any existing gain effects). One undo step.

        db=0 removes gain effects (unity). Typical range about -24..+12.
        """
        if not isinstance(db, (int, float)):
            raise ValueError("db must be numeric")
        db = float(db)
        if db < -60 or db > 24:
            raise ValueError("db must be in [-60, 24]")
        old = self.get_clip_gain_db(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            clip.effects = [e for e in (clip.effects or []) if e.get("type") != "gain"]
            applied = 0.0 if abs(db) < 0.05 else db
            if abs(applied) >= 0.05:
                clip.effects.append({"type": "gain", "db": applied})
            return {
                "clip_id": clip_id,
                "db": {"from": old, "to": applied},
                "agent_note": "Gain is clip effect; mix other clips with separate gains / ducking.",
            }

    def get_clip_opacity(self, clip_id: str) -> float:
        """Return opacity amount in [0,1]; default 1.0 if no opacity effect."""
        clip = self._find_clip(clip_id)
        amount = 1.0
        for fx in clip.effects or []:
            if fx.get("type") == "opacity" and isinstance(fx.get("amount"), (int, float)):
                amount = float(fx["amount"])
        return amount

    def set_clip_opacity(self, clip_id: str, amount: float) -> dict[str, Any]:
        """Set clip opacity 0..1 (replaces existing opacity effects). One undo.

        amount=1 removes the effect (fully opaque). Best seen on overlay tracks
        (composites over lower layers); on base track pads against transparent
        then black background.
        """
        if not isinstance(amount, (int, float)):
            raise ValueError("amount must be numeric")
        amount = float(amount)
        if not (0.0 <= amount <= 1.0):
            raise ValueError("amount must be in [0, 1]")
        old = self.get_clip_opacity(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            clip.effects = [e for e in (clip.effects or []) if e.get("type") != "opacity"]
            applied = 1.0 if amount >= 0.999 else amount
            if applied < 0.999:
                clip.effects.append({"type": "opacity", "amount": applied})
            return {
                "clip_id": clip_id,
                "opacity": {"from": old, "to": applied},
                "agent_note": "Opacity is a video alpha effect; re-export proxy to scrub.",
            }

    def history_status(self) -> dict[str, Any]:
        """Undo/redo stack depth + dirty/autosave (agent UI status)."""
        return {
            "undo_depth": len(self._undo_stack),
            "redo_depth": len(self._redo_stack),
            "can_undo": bool(self._undo_stack),
            "can_redo": bool(self._redo_stack),
            "dirty": bool(getattr(self, "_dirty", False)),
            "autosave": bool(getattr(self, "_autosave", False)),
            "has_clipboard": bool(self._clipboard),
            "has_effects_clipboard": bool(self._effects_clipboard),
            "effects_clipboard_count": (
                len(self._effects_clipboard) if self._effects_clipboard else 0
            ),
            "has_attributes_clipboard": bool(self._attributes_clipboard),
            "work_in_out": self.get_in_out(),
        }

    def make_subclip(
        self,
        clip_id: str,
        *,
        timeline_start: int | None = None,
        timeline_end: int | None = None,
        use_work_area: bool = False,
        place: str = "after",
        name: str | None = None,
    ) -> dict[str, Any]:
        """Duplicate a source range of a clip as a new clip (subclip).

        Range:
          - use_work_area=True: intersection of session In/Out with the clip
          - else timeline_start/timeline_end (absolute frames, end exclusive)
          - defaults: whole clip (same as duplicate footprint)

        place: after | start | clipboard
          - after: place after source clip on same track
          - start: place at timeline_start (or clip.start)
          - clipboard: copy blueprint only (no timeline place)
        """
        self._assert_clip_track_unlocked(clip_id)
        track, clip = self._find_clip_and_track(clip_id)
        if place not in ("after", "start", "clipboard"):
            raise ValueError("place must be after|start|clipboard")

        if use_work_area:
            io = self.get_in_out()
            if io.get("in_frame") is None or io.get("out_frame") is None:
                raise ValueError("work area In/Out not set")
            t0 = max(clip.start, int(io["in_frame"]))
            t1 = min(clip.end, int(io["out_frame"]))
            if t1 <= t0:
                raise ValueError("work area does not intersect this clip")
        else:
            t0 = clip.start if timeline_start is None else int(timeline_start)
            t1 = clip.end if timeline_end is None else int(timeline_end)
            if t0 < clip.start or t1 > clip.end or t1 <= t0:
                raise ValueError(
                    f"timeline range [{t0},{t1}) must lie inside clip "
                    f"[{clip.start},{clip.end})"
                )

        # Map timeline range → source frames
        def _src_at(tf: int) -> int:
            local = tf - clip.start
            if clip.speed != 1.0:
                s = clip.src_in + int(round(local * clip.speed))
            else:
                s = clip.src_in + local
            return min(max(s, clip.src_in), clip.src_out)

        src_in = _src_at(t0)
        src_out = _src_at(t1)
        if src_out <= src_in:
            src_out = min(clip.src_out, src_in + 1)

        bp = {
            "media": clip.media,
            "src_in": src_in,
            "src_out": src_out,
            "speed": clip.speed,
            "effects": [dict(e) for e in (clip.effects or [])],
            "position": dict(clip.position) if clip.position else None,
            "name": name or ((clip.name or "sub") + f"_{src_in}-{src_out}"),
            "color": clip.color,
            "source_track_kind": track.kind,
            "source_clip_id": clip.id,
            "duration_frames": max(1, round((src_out - src_in) / (clip.speed or 1.0))),
        }

        if place == "clipboard":
            self._clipboard = bp
            return {
                "placed": False,
                "clipboard": True,
                "src_in": src_in,
                "src_out": src_out,
                "name": bp["name"],
                "agent_note": "Subclip on session clipboard — paste_clip to place.",
            }

        place_at = clip.end if place == "after" else t0
        with self._mutate():
            track = self.project.track_by_id(track.id)
            media = self.project.media_by_id(clip.media)
            new_clip = self.project.add_clip(
                track, media, int(place_at), src_in, src_out,
            )
            new_clip.speed = clip.speed
            new_clip.effects = [dict(e) for e in (clip.effects or [])]
            if clip.position:
                new_clip.position = dict(clip.position)
            new_clip.name = bp["name"]
            if clip.color:
                new_clip.color = clip.color
            return {
                "placed": True,
                "clip_id": new_clip.id,
                "track_id": track.id,
                "start": new_clip.start,
                "end": new_clip.end,
                "src_in": src_in,
                "src_out": src_out,
                "name": new_clip.name,
                "from_clip_id": clip_id,
            }

    def waveform_peaks(
        self,
        *,
        path: str | Path | None = None,
        media_id: str | None = None,
        clip_id: str | None = None,
        num_peaks: int = 200,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Peak envelope for timeline waveforms. Caches under analysis/waveforms/."""
        resolved_media: str | None = media_id
        src: Path | None = Path(path) if path else None
        if clip_id is not None:
            clip = self._find_clip(clip_id)
            media = self.project.media_by_id(clip.media)
            resolved_media = media.id
            src = self.bundle.media_path(media.path)
        elif media_id is not None:
            media = self.project.media_by_id(media_id)
            src = self.bundle.media_path(media.path)
        if src is None:
            raise ValueError("provide path, media_id, or clip_id")

        if use_cache and resolved_media:
            cached = _load_cached_peaks(self.bundle.analysis_dir, resolved_media)
            if cached and cached.get("num_peaks") == num_peaks and cached.get("peaks"):
                cached = dict(cached)
                cached["cache_hit"] = True
                cached["media_id"] = resolved_media
                if clip_id:
                    cached["clip_id"] = clip_id
                return cached

        result = _extract_waveform_peaks(src, num_peaks=num_peaks)
        result["cache_hit"] = False
        if resolved_media:
            result["media_id"] = resolved_media
            if use_cache and result.get("peaks"):
                _save_cached_peaks(self.bundle.analysis_dir, resolved_media, result)
                result["cache_path"] = str(
                    self.bundle.analysis_dir / "waveforms" / f"{resolved_media}.json"
                )
        if clip_id:
            result["clip_id"] = clip_id
        return result

    def media_thumbnail(
        self,
        media_id: str,
        *,
        time_seconds: float = 0.1,
        width: int = 160,
        force: bool = False,
    ) -> dict[str, Any]:
        """JPEG poster frame for media bin (cached under analysis/thumbs/)."""
        media = self.project.media_by_id(media_id)
        if media.kind == "audio":
            raise ValueError("audio media has no video thumbnail")
        thumbs = self.bundle.analysis_dir / "thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        out = thumbs / f"{media_id}_{width}.jpg"
        if out.exists() and not force:
            return {
                "media_id": media_id,
                "path": str(out.resolve()),
                "cache_hit": True,
                "width": width,
            }
        src = self.bundle.media_path(media.path)
        if media.proxy_path:
            proxy = self.bundle.resolve_bundle_path(media.proxy_path)
            if proxy.exists():
                src = proxy
        if media.kind == "image":
            # still: scale once
            import subprocess
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-i", str(src),
                    "-frames:v", "1", "-vf", f"scale={int(width)}:-1",
                    str(out),
                ],
                capture_output=True, text=True,
            )
            if proc.returncode != 0 or not out.exists():
                raise RuntimeError(f"thumb failed:\n{(proc.stderr or '')[-800:]}")
            return {
                "media_id": media_id,
                "path": str(out.resolve()),
                "cache_hit": False,
                "width": width,
            }
        r = self.extract_frame(src, time_seconds, out, width=width)
        return {
            "media_id": media_id,
            "path": r["path"],
            "cache_hit": False,
            "width": width,
            "time_seconds": time_seconds,
        }

    def _apply_effect_unlocked(self, clip_id: str, effect: dict) -> Clip:
        """Validate + append effect. Caller must hold ``_mutate`` when mutating."""
        clip = self._find_clip(clip_id)
        etype = effect.get("type")
        if etype not in KNOWN_EFFECT_TYPES:
            raise ValueError(
                f"unknown effect type {etype!r}; supported: {sorted(KNOWN_EFFECT_TYPES)}"
            )
        if etype == "fade":
            direction = effect.get("direction")
            if direction not in ("in", "out"):
                raise ValueError("fade effect requires direction 'in' or 'out'")
            duration_frames = effect.get("duration_frames")
            if not isinstance(duration_frames, int) or duration_frames <= 0:
                raise ValueError(
                    "fade effect requires a positive integer duration_frames"
                )
            if duration_frames > clip.duration_frames:
                raise ValueError(
                    f"fade duration_frames ({duration_frames}) exceeds clip "
                    f"duration ({clip.duration_frames})"
                )
        elif etype == "opacity":
            amount = effect.get("amount")
            if not isinstance(amount, (int, float)) or not (0.0 <= float(amount) <= 1.0):
                raise ValueError("opacity effect requires amount in [0, 1]")
        elif etype == "gain":
            db = effect.get("db")
            if not isinstance(db, (int, float)):
                raise ValueError("gain effect requires a numeric 'db' field")
        elif etype == "text":
            content = effect.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("text effect requires non-empty string 'content'")
            position = effect.get("position", "bottom")
            if position not in TEXT_POSITIONS:
                raise ValueError(
                    f"text effect position must be one of {sorted(TEXT_POSITIONS)}, "
                    f"got {position!r}"
                )
            size = effect.get("size", 48)
            if not isinstance(size, int) or size <= 0:
                raise ValueError("text effect 'size' must be a positive integer")
            border_width = effect.get("border_width", 2)
            if not isinstance(border_width, int) or border_width < 0:
                raise ValueError("text effect 'border_width' must be a non-negative integer")
        elif etype == "subtitles":
            path = effect.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("subtitles effect requires non-empty string 'path' to an .srt/.ass file")
            if not Path(path).exists():
                raise FileNotFoundError(f"subtitles effect path not found: {path}")
        elif etype == "blur":
            amount = effect.get("amount", 5.0)
            if not isinstance(amount, (int, float)) or amount <= 0:
                raise ValueError("blur effect 'amount' must be a positive number")
        elif etype == "vignette":
            strength = effect.get("strength", 1.0)
            if not isinstance(strength, (int, float)) or strength <= 0:
                raise ValueError("vignette effect 'strength' must be a positive number")
        elif etype == "chroma_key":
            similarity = effect.get("similarity", 0.15)
            if not isinstance(similarity, (int, float)) or not (0.0 < similarity <= 1.0):
                raise ValueError("chroma_key effect 'similarity' must be in (0, 1]")
            blend = effect.get("blend", 0.05)
            if not isinstance(blend, (int, float)) or not (0.0 <= blend <= 1.0):
                raise ValueError("chroma_key effect 'blend' must be in [0, 1]")
        elif etype == "luma_key":
            threshold = effect.get("threshold", 0.1)
            if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
                raise ValueError("luma_key effect 'threshold' must be in [0, 1]")
            tolerance = effect.get("tolerance", 0.1)
            if not isinstance(tolerance, (int, float)) or not (0.0 <= tolerance <= 1.0):
                raise ValueError("luma_key effect 'tolerance' must be in [0, 1]")
        elif etype == "curves":
            preset = effect.get("preset")
            if preset not in CURVES_PRESETS:
                raise ValueError(f"curves effect 'preset' must be one of {sorted(CURVES_PRESETS)}")
        elif etype == "sharpen":
            amount = effect.get("amount", 1.0)
            if not isinstance(amount, (int, float)) or not (0.0 < amount <= 5.0):
                raise ValueError("sharpen effect 'amount' must be in (0, 5]")
        elif etype == "film_grain":
            amount = effect.get("amount", 20.0)
            if not isinstance(amount, (int, float)) or not (0.0 < amount <= 100.0):
                raise ValueError("film_grain effect 'amount' must be in (0, 100]")
        elif etype == "glow":
            amount = effect.get("amount", 12.0)
            if not isinstance(amount, (int, float)) or not (0.0 < amount <= 50.0):
                raise ValueError("glow effect 'amount' must be in (0, 50]")
            intensity = effect.get("intensity", 0.7)
            if not isinstance(intensity, (int, float)) or not (0.0 < intensity <= 1.0):
                raise ValueError("glow effect 'intensity' must be in (0, 1]")
        elif etype == "lut3d":
            path = effect.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("lut3d effect requires non-empty string 'path' to a .cube/.3dl file")
            if not Path(path).exists():
                raise FileNotFoundError(f"lut3d effect path not found: {path}")
        elif etype == "ken_burns":
            for key, lo, hi in (
                ("zoom_start", 1.0, 10.0),
                ("zoom_end", 1.0, 10.0),
                ("x_start", 0.0, 1.0),
                ("y_start", 0.0, 1.0),
                ("x_end", 0.0, 1.0),
                ("y_end", 0.0, 1.0),
            ):
                default = 1.0 if key.startswith("zoom") else 0.5
                val = effect.get(key, default)
                if not isinstance(val, (int, float)) or not (lo <= float(val) <= hi):
                    raise ValueError(f"ken_burns effect {key!r} must be in [{lo}, {hi}]")
        elif etype == "white_balance":
            temperature = effect.get("temperature", 6500)
            if not isinstance(temperature, (int, float)) or not (1000 <= temperature <= 40000):
                raise ValueError("white_balance effect 'temperature' must be in [1000, 40000] Kelvin")
            mix = effect.get("mix", 1.0)
            if not isinstance(mix, (int, float)) or not (0.0 <= mix <= 1.0):
                raise ValueError("white_balance effect 'mix' must be in [0, 1]")
        elif etype == "shape_mask":
            shape = effect.get("shape", "circle")
            if shape not in SHAPE_MASK_SHAPES:
                raise ValueError(
                    f"shape_mask 'shape' must be one of {sorted(SHAPE_MASK_SHAPES)}, got {shape!r}"
                )
            for key, default in (("cx", 0.5), ("cy", 0.5), ("size", 0.5), ("feather", 0.05)):
                val = effect.get(key, default)
                if not isinstance(val, (int, float)) or not (0.0 <= float(val) <= 1.0):
                    raise ValueError(f"shape_mask {key!r} must be in [0, 1]")
            if shape == "rect":
                for key, default in (("width", 0.5), ("height", 0.5)):
                    val = effect.get(key, default)
                    if not isinstance(val, (int, float)) or not (0.0 < float(val) <= 1.0):
                        raise ValueError(f"shape_mask {key!r} must be in (0, 1]")
        elif etype == "compression":
            ratio = effect.get("ratio", 4.0)
            if not isinstance(ratio, (int, float)) or not (1.0 <= ratio <= 20.0):
                raise ValueError("compression effect 'ratio' must be in [1, 20]")
            for field_name in ("threshold_db", "attack_ms", "release_ms", "makeup_db"):
                if field_name in effect and not isinstance(effect[field_name], (int, float)):
                    raise ValueError(f"compression effect {field_name!r} must be numeric")
        elif etype == "noise_reduction":
            amount = effect.get("amount", 12.0)
            if not isinstance(amount, (int, float)) or not (0.01 <= amount <= 97.0):
                raise ValueError("noise_reduction effect 'amount' must be in [0.01, 97]")
        elif etype == "audio_eq":
            frequency_hz = effect.get("frequency_hz")
            if not isinstance(frequency_hz, (int, float)) or not (20.0 <= frequency_hz <= 20000.0):
                raise ValueError("audio_eq effect requires 'frequency_hz' in [20, 20000]")
            gain_db = effect.get("gain_db", 0.0)
            if not isinstance(gain_db, (int, float)) or not (-24.0 <= gain_db <= 24.0):
                raise ValueError("audio_eq effect 'gain_db' must be in [-24, 24]")
            q = effect.get("q", 1.0)
            if not isinstance(q, (int, float)) or not (0.0 < q <= 10.0):
                raise ValueError("audio_eq effect 'q' must be in (0, 10]")
        elif etype == "crop":
            width, height = effect.get("width"), effect.get("height")
            if not isinstance(width, int) or width <= 0:
                raise ValueError("crop effect requires a positive integer 'width'")
            if not isinstance(height, int) or height <= 0:
                raise ValueError("crop effect requires a positive integer 'height'")
        elif etype == "rotate":
            degrees = effect.get("degrees")
            if not isinstance(degrees, (int, float)):
                raise ValueError("rotate effect requires a numeric 'degrees'")
        clip.effects.append(dict(effect))
        return clip

    def apply_effect(self, clip_id: str, effect: dict) -> Clip:
        """Append a deterministic effect (ARCHITECTURE.md section 5.8) to a clip.

        Validated here so an agent gets an immediate, specific error instead of
        a cryptic ffmpeg failure at export time. See KNOWN_EFFECT_TYPES for the
        supported vocabulary; each type documents its own required fields.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            return self._apply_effect_unlocked(clip_id, effect)

    def apply_effect_to_clips(
        self,
        clip_ids: list[str],
        effect: dict,
    ) -> dict[str, Any]:
        """Append the same effect to many clips (one undo step)."""
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        ids = list(dict.fromkeys(clip_ids))
        with self._mutate():
            applied: list[str] = []
            for cid in ids:
                track, _ = self._find_clip_and_track(cid)
                if track.locked:
                    raise ValueError(f"track {track.id} is locked")
                self._apply_effect_unlocked(cid, effect)
                applied.append(cid)
            return {
                "effect_type": effect.get("type"),
                "applied": applied,
                "count": len(applied),
            }

    def set_clip_crop(
        self,
        clip_id: str,
        width: int,
        height: int,
        *,
        x: str | int | None = None,
        y: str | int | None = None,
    ) -> dict[str, Any]:
        """Set crop effect (replaces existing crop). width/height in pixels.

        x/y optional; when omitted ffmpeg centers the crop.
        """
        self._assert_clip_track_unlocked(clip_id)
        if not isinstance(width, int) or width <= 0:
            raise ValueError("width must be a positive int")
        if not isinstance(height, int) or height <= 0:
            raise ValueError("height must be a positive int")
        fx: dict[str, Any] = {"type": "crop", "width": width, "height": height}
        if x is not None:
            fx["x"] = x
        if y is not None:
            fx["y"] = y
        with self._mutate():
            clip = self._find_clip(clip_id)
            clip.effects = [e for e in (clip.effects or []) if e.get("type") != "crop"]
            self._apply_effect_unlocked(clip_id, fx)
            return {
                "clip_id": clip_id,
                "crop": {"width": width, "height": height, "x": x, "y": y},
            }

    def find_gaps(
        self,
        track_id: str | None = None,
        *,
        from_frame: int = 0,
        min_gap_frames: int = 1,
    ) -> dict[str, Any]:
        """Report holes between clips (and leading gap after from_frame)."""
        if min_gap_frames < 1:
            raise ValueError("min_gap_frames must be >= 1")
        tracks = (
            [self.project.track_by_id(track_id)]
            if track_id is not None
            else list(self.project.tracks)
        )
        out: list[dict[str, Any]] = []
        for track in tracks:
            ordered = [
                c for c in track.clips_in_order()
                if c.end > from_frame
            ]
            cursor = int(from_frame)
            gaps: list[dict[str, Any]] = []
            for c in ordered:
                if c.start > cursor and (c.start - cursor) >= min_gap_frames:
                    gaps.append({
                        "start": cursor,
                        "end": c.start,
                        "frames": c.start - cursor,
                    })
                cursor = max(cursor, c.end)
            out.append({
                "track_id": track.id,
                "kind": track.kind,
                "gaps": gaps,
                "gap_count": len(gaps),
                "gap_frames_total": sum(g["frames"] for g in gaps),
            })
        return {
            "from_frame": from_frame,
            "tracks": out,
            "total_gaps": sum(t["gap_count"] for t in out),
        }

    def close_all_gaps(self, *, from_frame: int = 0) -> dict[str, Any]:
        """close_gaps on every track (one undo)."""
        with self._mutate():
            results: list[dict[str, Any]] = []
            for track in list(self.project.tracks):
                if track.locked:
                    results.append({
                        "track_id": track.id, "skipped": True, "reason": "locked",
                    })
                    continue
                # inline pack without nested mutate
                ordered = track.clips_in_order()
                if not ordered:
                    results.append({
                        "track_id": track.id, "moved": [], "cursor": from_frame,
                    })
                    continue
                cursor = int(from_frame)
                moved: list[dict[str, Any]] = []
                for c in ordered:
                    if c.start < from_frame:
                        continue
                    old = c.start
                    if c.transition_in is not None:
                        c.transition_in = None
                    c.start = cursor
                    if old != cursor:
                        moved.append({"clip_id": c.id, "from": old, "to": cursor})
                    cursor = c.end
                results.append({
                    "track_id": track.id, "moved": moved, "cursor": cursor,
                })
            return {
                "from_frame": from_frame,
                "tracks": results,
                "moved_total": sum(len(r.get("moved") or []) for r in results),
            }

    def remove_empty_tracks(self, *, keep_one_per_kind: bool = True) -> dict[str, Any]:
        """Delete tracks with no clips.

        keep_one_per_kind=True: leave one empty video and one empty audio if
        that would otherwise wipe the last track of that kind (agents can still
        place media). Locked empty tracks are skipped.
        """
        with self._mutate():
            removed: list[str] = []
            skipped: list[dict[str, Any]] = []
            # Count empties we might keep
            by_kind_empty: dict[str, list] = {"video": [], "audio": []}
            nonempty_kinds: set[str] = set()
            for t in self.project.tracks:
                if t.clips:
                    nonempty_kinds.add(t.kind)
                else:
                    by_kind_empty.setdefault(t.kind, []).append(t)

            to_remove: list = []
            for kind, empties in by_kind_empty.items():
                keep_n = 0
                if keep_one_per_kind and kind not in nonempty_kinds and empties:
                    keep_n = 1
                # prefer keeping first empty of kind
                for i, t in enumerate(empties):
                    if t.locked:
                        skipped.append({"track_id": t.id, "reason": "locked"})
                        continue
                    if i < keep_n:
                        skipped.append({"track_id": t.id, "reason": "keep_one_per_kind"})
                        continue
                    to_remove.append(t)

            for t in to_remove:
                tid = t.id
                self.project.tracks.remove(t)
                for other in self.project.tracks:
                    if other.duck is not None and other.duck.get("against") == tid:
                        other.duck = None
                removed.append(tid)
            return {
                "removed": removed,
                "count": len(removed),
                "skipped": skipped,
                "remaining_tracks": len(self.project.tracks),
            }

    def list_tracks(self) -> dict[str, Any]:
        """Summarize tracks for agents/UI."""
        items = []
        for i, t in enumerate(self.project.tracks):
            items.append({
                "track_id": t.id,
                "index": i,
                "kind": t.kind,
                "name": t.name,
                "clip_count": len(t.clips),
                "muted": bool(t.muted),
                "solo": bool(t.solo),
                "locked": bool(t.locked),
                "has_duck": t.duck is not None,
            })
        return {"count": len(items), "tracks": items}

    def add_transition(self, clip_id: str, transition_type: str, duration_frames: int) -> Clip:
        """Dissolve ``clip_id`` in from whatever clip precedes it on its track.

        Requires the boundary to currently be a clean hard cut (this clip's
        start exactly equals the previous clip's end) — you can only *add* a
        transition where there's an existing clean edit, not arbitrarily
        overlap unrelated clips. Shortens the combined timeline by
        duration_frames (start moves earlier by that much; see render/ffmpeg.py
        for how this overlap is rendered as an actual crossfade).
        """
        with self._mutate():
            if transition_type not in KNOWN_TRANSITION_TYPES:
                raise ValueError(
                    f"unknown transition type {transition_type!r}; "
                    f"supported: {sorted(KNOWN_TRANSITION_TYPES)}"
                )
            if not isinstance(duration_frames, int) or duration_frames <= 0:
                raise ValueError("add_transition requires a positive integer duration_frames")

            track, clip = self._find_clip_and_track(clip_id)
            if clip.transition_in is not None:
                raise ValueError(f"clip {clip_id} already has a transition_in; remove it first")

            ordered = track.clips_in_order()
            idx = ordered.index(clip)
            if idx == 0:
                raise ValueError(f"clip {clip_id} is first on its track — nothing to dissolve from")
            prev = ordered[idx - 1]
            if clip.start != prev.end:
                raise ValueError(
                    f"clip {clip_id} is not a clean cut from {prev.id} "
                    f"(start={clip.start}, prev.end={prev.end}) — "
                    "transitions can only be added at an existing hard cut"
                )
            if duration_frames > min(prev.duration_frames, clip.duration_frames):
                raise ValueError(
                    f"transition duration_frames ({duration_frames}) exceeds the "
                    f"shorter of the two clips ({min(prev.duration_frames, clip.duration_frames)})"
                )

            clip.transition_in = {"type": transition_type, "duration_frames": duration_frames}
            clip.start -= duration_frames
            return clip

    def place_after(
        self,
        after_clip_id: str,
        media_id: str,
        src_in: int = 0,
        src_out: int | None = None,
        transition_type: str | None = None,
        transition_frames: int | None = None,
    ) -> Clip:
        """Place media as the next hard-cut clip after ``after_clip_id``.

        Dogfood friction fix: agents kept trying to place pre-overlapped then
        call add_transition (rejected). This does the hard cut first, then
        optionally add_transition in one call — the order the API requires.
        """
        with self._mutate():
            track, prev = self._find_clip_and_track(after_clip_id)
            media = self.project.media_by_id(media_id)
            if src_out is None:
                src_out = media.duration_frames
            if not isinstance(src_out, int) or src_out <= src_in:
                raise ValueError(f"need src_out > src_in, got src_in={src_in} src_out={src_out}")
            # model.add_clip takes src_in/src_out (source frame range), not duration.
            clip = self.project.add_clip(track, media, prev.end, src_in, src_out)
        if transition_type is not None:
            if transition_frames is None:
                raise ValueError("place_after with transition_type also needs transition_frames")
            return self.add_transition(clip.id, transition_type, transition_frames)
        return clip

    def remove_transition(self, clip_id: str) -> Clip:
        with self._mutate():
            clip = self._find_clip(clip_id)
            if clip.transition_in is None:
                raise ValueError(f"clip {clip_id} has no transition_in to remove")
            clip.start += clip.transition_in["duration_frames"]
            clip.transition_in = None
            return clip

    def set_speed(self, clip_id: str, speed: float) -> Clip:
        """Change a clip's playback rate (1.0 = normal). src_in/src_out are
        untouched — this changes how much timeline space the same source
        material occupies (see Clip.timeline_duration_frames), not which
        frames are used. Like move_clip/trim_clip, this doesn't proactively
        re-check contiguity with whatever else is on the track — that's
        validated at export time (render/ffmpeg.py), consistent with how
        those two already behave.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            if not isinstance(speed, (int, float)) or speed <= 0:
                raise ValueError(f"speed must be a positive number, got {speed!r}")
            # Practical range for single atempo / setpts path
            if float(speed) < 0.25 or float(speed) > 4.0:
                raise ValueError("speed must be in [0.25, 4.0]")
            clip = self._find_clip(clip_id)
            clip.speed = float(speed)
            return clip

    def stretch_to(
        self,
        clip_id: str,
        target_duration_frames: int,
        *,
        clamp: bool = True,
    ) -> dict[str, Any]:
        """Rate-stretch a clip so its timeline footprint matches target frames.

        Adjusts speed = source_frames / target_duration_frames (clamped to
        [0.25, 4.0] when clamp=True). One undo. Does not ripple neighbors.
        """
        if not isinstance(target_duration_frames, int) or target_duration_frames <= 0:
            raise ValueError("target_duration_frames must be a positive int")
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            src_len = clip.duration_frames  # source frames, not timeline
            if src_len <= 0:
                raise ValueError("clip has empty source range")
            raw_speed = src_len / float(target_duration_frames)
            speed = raw_speed
            clamped = False
            if clamp:
                if speed < 0.25:
                    speed = 0.25
                    clamped = True
                elif speed > 4.0:
                    speed = 4.0
                    clamped = True
            else:
                if speed < 0.25 or speed > 4.0:
                    raise ValueError(
                        f"required speed {raw_speed:.4f} outside [0.25, 4.0]; "
                        "pass clamp=True or pick another duration"
                    )
            old_speed = clip.speed
            old_dur = clip.timeline_duration_frames
            clip.speed = float(speed)
            return {
                "clip_id": clip_id,
                "speed": {"from": old_speed, "to": clip.speed},
                "duration_frames": {
                    "from": old_dur,
                    "to": clip.timeline_duration_frames,
                    "target": target_duration_frames,
                },
                "raw_speed": round(raw_speed, 6),
                "clamped": clamped,
                "agent_note": (
                    "Neighbors not rippled. close_gaps / ripple_nudge if packing needed."
                ),
            }

    def clips_on_track(
        self,
        track_id: str,
        *,
        ordered: bool = True,
    ) -> dict[str, Any]:
        """List clips on a track (agent helper for batch ops)."""
        track = self.project.track_by_id(track_id)
        clips = track.clips_in_order() if ordered else list(track.clips)
        items = [
            {
                "clip_id": c.id,
                "start": c.start,
                "end": c.end,
                "media_id": c.media,
                "src_in": c.src_in,
                "src_out": c.src_out,
                "speed": c.speed,
                "name": c.name,
                "muted": c.muted,
            }
            for c in clips
        ]
        return {
            "track_id": track_id,
            "kind": track.kind,
            "count": len(items),
            "clips": items,
        }

    def set_position(self, clip_id: str, x: float, y: float, scale: float) -> Clip:
        """Place a clip as a picture-in-picture box instead of full-frame —
        only takes effect when the clip is on an overlay video track (any
        video track after the first; see render/ffmpeg.py's z-order
        convention). ``scale`` (0 < scale <= 1) is the box's size as a
        fraction of the canvas, aspect preserved. ``x``/``y`` (each 0..1)
        place the box's top-left corner as a fraction of the room it has to
        move in (canvas size minus box size) — 0 is flush against that edge,
        1 is flush against the opposite edge, so any value in range keeps the
        whole box on-canvas by construction.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            if not isinstance(scale, (int, float)) or not (0.0 < scale <= 1.0):
                raise ValueError(f"scale must be in (0, 1], got {scale!r}")
            if not isinstance(x, (int, float)) or not (0.0 <= x <= 1.0):
                raise ValueError(f"x must be in [0, 1], got {x!r}")
            if not isinstance(y, (int, float)) or not (0.0 <= y <= 1.0):
                raise ValueError(f"y must be in [0, 1], got {y!r}")
            clip = self._find_clip(clip_id)
            clip.position = {"x": float(x), "y": float(y), "scale": float(scale)}
            return clip

    def freeze_frame(
        self,
        clip_id: str,
        *,
        at_timeline_frame: int | None = None,
        duration_frames: int = 30,
        track_id: str | None = None,
        start: int | None = None,
    ) -> dict[str, Any]:
        """Extract one frame from a video clip and place it as a still.

        at_timeline_frame: absolute timeline frame (default = mid of clip).
        duration_frames: how long the still holds on the timeline.
        Places on same track after the clip unless track_id/start given.
        """
        import subprocess
        import uuid

        from .model import IMAGE_VIRTUAL_DURATION_FRAMES

        self._assert_clip_track_unlocked(clip_id)
        track, clip = self._find_clip_and_track(clip_id)
        media = self.project.media_by_id(clip.media)
        if media.kind == "audio":
            raise ValueError("freeze_frame needs a video/image clip")
        if duration_frames <= 0:
            raise ValueError("duration_frames must be positive")

        if at_timeline_frame is None:
            at_timeline_frame = clip.start + max(0, clip.timeline_duration_frames // 2)
        if not (clip.start <= at_timeline_frame < clip.end):
            raise ValueError("at_timeline_frame must be inside the clip")

        local = at_timeline_frame - clip.start
        if clip.speed != 1.0:
            src_frame = clip.src_in + int(round(local * clip.speed))
        else:
            src_frame = clip.src_in + local
        src_frame = min(max(src_frame, clip.src_in), max(clip.src_in, clip.src_out - 1))
        src_t = self.project.timebase.frames_to_seconds(src_frame)

        src_path = self.bundle.media_path(media.path)
        self.bundle.media_dir.mkdir(parents=True, exist_ok=True)
        name = f"freeze_{clip_id}_{uuid.uuid4().hex[:6]}.jpg"
        dest = self.bundle.media_dir / name
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner",
                "-ss", f"{src_t:.3f}",
                "-i", str(src_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(dest),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not dest.exists():
            raise RuntimeError(
                f"freeze_frame extract failed:\n{(proc.stderr or '')[-1200:]}"
            )

        place_track = track_id or track.id
        place_start = start if start is not None else clip.end
        with self._mutate():
            still = self.project.add_media(
                kind="image",
                path=name,
                duration_frames=IMAGE_VIRTUAL_DURATION_FRAMES,
                has_audio=False,
                origin={
                    "freeze_from_clip": clip_id,
                    "src_frame": src_frame,
                    "src_time": src_t,
                },
            )
            tr = self.project.track_by_id(place_track)
            if tr.locked:
                raise ValueError(f"track {place_track} is locked")
            new_clip = self.project.add_clip(
                tr, still, int(place_start), 0, int(duration_frames),
            )
            new_clip.name = (clip.name or "freeze") + "_still"
            if clip.color:
                new_clip.color = clip.color
            return {
                "clip_id": new_clip.id,
                "media_id": still.id,
                "path": name,
                "src_frame": src_frame,
                "src_time_seconds": round(src_t, 3),
                "duration_frames": duration_frames,
                "start": new_clip.start,
                "track_id": place_track,
                "agent_note": "Still image clip; export holds the frame for duration_frames.",
            }

    def reverse_clip(
        self,
        clip_id: str,
        *,
        replace: bool = True,
    ) -> dict[str, Any]:
        """Re-encode the clip's source range reversed and use it as new media.

        replace=True: retarget this clip to reversed media (src_in=0, full length).
        Timeline start/duration preserved when possible (speed reset to 1.0).
        """
        import subprocess
        import uuid

        self._assert_clip_track_unlocked(clip_id)
        track, clip = self._find_clip_and_track(clip_id)
        media = self.project.media_by_id(clip.media)
        if media.kind == "image":
            raise ValueError("cannot reverse a still image")

        src_path = self.bundle.media_path(media.path)
        fps = float(self.project.timebase.fps or 30.0)
        t0 = self.project.timebase.frames_to_seconds(clip.src_in)
        t1 = self.project.timebase.frames_to_seconds(clip.src_out)
        if t1 <= t0:
            raise ValueError("empty source range")

        self.bundle.media_dir.mkdir(parents=True, exist_ok=True)
        tag = uuid.uuid4().hex[:6]
        if media.kind == "audio" or (not media.has_audio and media.kind != "video"):
            # audio-only reverse
            name = f"rev_{clip_id}_{tag}.m4a"
            dest = self.bundle.media_dir / name
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner",
                    "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                    "-i", str(src_path),
                    "-af", "areverse",
                    "-c:a", "aac", str(dest),
                ],
                capture_output=True, text=True,
            )
            kind: MediaKind = "audio"
            has_audio = True
        else:
            name = f"rev_{clip_id}_{tag}.mp4"
            dest = self.bundle.media_dir / name
            # reverse video (+audio if present)
            vf = "reverse"
            af = "areverse" if media.has_audio else None
            cmd = [
                "ffmpeg", "-y", "-hide_banner",
                "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                "-i", str(src_path),
                "-vf", vf,
            ]
            if af:
                cmd += ["-af", af, "-c:a", "aac"]
            else:
                cmd += ["-an"]
            cmd += [
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                str(dest),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            kind = "video"
            has_audio = bool(media.has_audio)

        if proc.returncode != 0 or not dest.exists():
            raise RuntimeError(
                f"reverse_clip encode failed:\n{(proc.stderr or '')[-1500:]}"
            )

        from .render.probe import probe as _probe
        info = _probe(dest)
        dur_f = self.project.timebase.seconds_to_frames(info.duration_seconds)

        with self._mutate():
            new_media = self.project.add_media(
                kind=kind,
                path=name,
                duration_frames=dur_f,
                has_audio=has_audio and info.has_audio if kind == "video" else has_audio,
                origin={
                    "reversed_from_clip": clip_id,
                    "source_media": media.id,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                },
            )
            if replace:
                old = {
                    "media": clip.media,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "speed": clip.speed,
                }
                clip.media = new_media.id
                clip.src_in = 0
                clip.src_out = dur_f
                clip.speed = 1.0
                # Keep timeline footprint close: if durations differ slightly, ok
                return {
                    "clip_id": clip_id,
                    "media_id": new_media.id,
                    "path": name,
                    "duration_frames": dur_f,
                    "replaced": True,
                    "from": old,
                    "agent_note": "Clip now points at reversed media; re-export proxy.",
                }
            # place after as new clip
            tr = track
            new_clip = self.project.add_clip(
                tr, new_media, clip.end, 0, dur_f,
            )
            return {
                "clip_id": new_clip.id,
                "media_id": new_media.id,
                "path": name,
                "duration_frames": dur_f,
                "replaced": False,
            }

    def stabilize_clip(
        self,
        clip_id: str,
        *,
        replace: bool = True,
        strength: float = 1.0,
    ) -> dict[str, Any]:
        """Re-encode clip source range with ffmpeg ``deshake`` (video only).

        strength scales deshake rx/ry (1.0 → 64/64; range about 0.25–2).
        replace=True retargets this clip (src 0..dur, speed 1.0).
        """
        import subprocess
        import uuid

        self._assert_clip_track_unlocked(clip_id)
        track, clip = self._find_clip_and_track(clip_id)
        media = self.project.media_by_id(clip.media)
        if media.kind != "video":
            raise ValueError("stabilize_clip requires a video clip")
        if not isinstance(strength, (int, float)) or not (0.1 <= float(strength) <= 3.0):
            raise ValueError("strength must be in [0.1, 3]")
        strength = float(strength)
        rx = max(16, min(128, int(round(64 * strength))))
        ry = rx

        src_path = self.bundle.media_path(media.path)
        t0 = self.project.timebase.frames_to_seconds(clip.src_in)
        t1 = self.project.timebase.frames_to_seconds(clip.src_out)
        if t1 <= t0:
            raise ValueError("empty source range")

        self.bundle.media_dir.mkdir(parents=True, exist_ok=True)
        tag = uuid.uuid4().hex[:6]
        name = f"stab_{clip_id}_{tag}.mp4"
        dest = self.bundle.media_dir / name
        vf = f"deshake=rx={rx}:ry={ry}"
        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
            "-i", str(src_path),
            "-vf", vf,
        ]
        if media.has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]
        cmd += [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not dest.exists():
            raise RuntimeError(
                f"stabilize_clip encode failed:\n{(proc.stderr or '')[-1500:]}"
            )

        from .render.probe import probe as _probe
        info = _probe(dest)
        dur_f = self.project.timebase.seconds_to_frames(info.duration_seconds)

        with self._mutate():
            new_media = self.project.add_media(
                kind="video",
                path=name,
                duration_frames=dur_f,
                has_audio=bool(media.has_audio and info.has_audio),
                origin={
                    "stabilized_from_clip": clip_id,
                    "source_media": media.id,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "deshake_rx": rx,
                    "deshake_ry": ry,
                },
            )
            if replace:
                old = {
                    "media": clip.media,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "speed": clip.speed,
                }
                clip.media = new_media.id
                clip.src_in = 0
                clip.src_out = dur_f
                clip.speed = 1.0
                return {
                    "clip_id": clip_id,
                    "media_id": new_media.id,
                    "path": name,
                    "duration_frames": dur_f,
                    "rx": rx,
                    "ry": ry,
                    "replaced": True,
                    "from": old,
                    "agent_note": "Stabilized media; re-export proxy. deshake is mild — not cinematic gyro.",
                }
            new_clip = self.project.add_clip(track, new_media, clip.end, 0, dur_f)
            return {
                "clip_id": new_clip.id,
                "media_id": new_media.id,
                "path": name,
                "duration_frames": dur_f,
                "replaced": False,
                "rx": rx,
                "ry": ry,
            }

    def export_markers(
        self,
        path: str | Path | None = None,
        *,
        format: str = "youtube",
    ) -> dict[str, Any]:
        """Export timeline markers as YouTube chapters, CSV, or JSON.

        format: youtube | csv | json
        path=None → return body only (no file write).
        """
        if format not in ("youtube", "csv", "json"):
            raise ValueError("format must be youtube|csv|json")
        fps = float(self.project.timebase.fps or 30.0)
        markers = sorted(self.project.markers, key=lambda m: m.frame)
        if format == "youtube":
            # YouTube needs a 0:00 line first for chapters
            lines: list[str] = []
            if not markers or markers[0].frame > 0:
                lines.append("0:00 Intro")
            for m in markers:
                total_s = int(m.frame // max(1, int(round(fps))))
                # also include remainder as mm:ss from total seconds
                total_s = int(round(m.frame / fps))
                hh = total_s // 3600
                mm = (total_s % 3600) // 60
                ss = total_s % 60
                if hh > 0:
                    stamp = f"{hh}:{mm:02d}:{ss:02d}"
                else:
                    stamp = f"{mm}:{ss:02d}"
                label = (m.label or m.id).strip() or "Chapter"
                lines.append(f"{stamp} {label}")
            body = "\n".join(lines) + ("\n" if lines else "")
        elif format == "csv":
            rows = ["frame,seconds,tc,label,color,id"]
            for m in markers:
                tc = self.frames_to_tc(m.frame)["tc"]
                sec = round(m.frame / fps, 3)
                lab = (m.label or "").replace(",", " ")
                rows.append(
                    f"{m.frame},{sec},{tc},{lab},{m.color},{m.id}"
                )
            body = "\n".join(rows) + "\n"
        else:
            body = json.dumps(
                {
                    "fps": fps,
                    "markers": [
                        {
                            **m.to_dict(),
                            "time_seconds": round(m.frame / fps, 3),
                            "tc": self.frames_to_tc(m.frame)["tc"],
                        }
                        for m in markers
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ) + "\n"

        written = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            written = str(p.resolve())
        return {
            "format": format,
            "count": len(markers),
            "path": written,
            "body": body,
        }

    def import_markers(
        self,
        text: str,
        *,
        format: str = "youtube",
        replace: bool = False,
        default_color: str = "#7c9cff",
    ) -> dict[str, Any]:
        """Import markers from YouTube chapter text or CSV.

        youtube lines: ``M:SS Label`` / ``H:MM:SS Label`` / ``0:00 Intro``
        csv: frame,seconds,tc,label,color,id (header optional; uses frame or tc)
        replace=True clears existing markers first.
        """
        if format not in ("youtube", "csv"):
            raise ValueError("format must be youtube|csv")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is empty")
        fps = float(self.project.timebase.fps or 30.0)
        parsed: list[dict[str, Any]] = []

        if format == "youtube":
            import re
            for raw in text.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(
                    r"^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$",
                    line,
                )
                if not m:
                    continue
                stamp, label = m.group(1), m.group(2).strip()
                parts = [int(x) for x in stamp.split(":")]
                if len(parts) == 2:
                    mm, ss = parts
                    seconds = mm * 60 + ss
                else:
                    hh, mm, ss = parts
                    seconds = hh * 3600 + mm * 60 + ss
                frame = int(round(seconds * fps))
                parsed.append({"frame": frame, "label": label, "color": default_color})
        else:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                return {"added": [], "count": 0}
            start = 0
            if lines[0].lower().startswith("frame") or "label" in lines[0].lower():
                start = 1
            for ln in lines[start:]:
                cols = [c.strip() for c in ln.split(",")]
                if not cols:
                    continue
                frame = None
                label = ""
                color = default_color
                if cols[0].isdigit():
                    frame = int(cols[0])
                    if len(cols) >= 4:
                        label = cols[3]
                    elif len(cols) >= 2 and not cols[1].replace(".", "", 1).isdigit():
                        label = cols[1]
                    if len(cols) >= 5 and cols[4].startswith("#"):
                        color = cols[4]
                else:
                    # try tc in col0 or col2
                    for col in cols[:3]:
                        try:
                            frame = self.tc_to_frames(col)["frame"]
                            break
                        except ValueError:
                            continue
                    if len(cols) >= 4:
                        label = cols[3]
                if frame is None:
                    continue
                parsed.append({
                    "frame": max(0, int(frame)),
                    "label": label or f"M{frame}",
                    "color": color,
                })

        with self._mutate():
            if replace:
                self.project.markers.clear()
            added: list[dict[str, Any]] = []
            for p in parsed:
                m = self.project.add_marker(
                    p["frame"], label=p["label"], color=p["color"],
                )
                added.append(m.to_dict())
            return {
                "format": format,
                "added": added,
                "count": len(added),
                "replaced": replace,
            }

    def export_edl(
        self,
        path: str | Path | None = None,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Export a simple CMX3600-style EDL of the base video track.

        One event per clip (source in/out + record in/out). Not a full AAF.
        path=None → return body only.
        """
        fps = float(self.project.timebase.fps or 30.0)
        fps_i = max(1, int(round(fps)))
        video_tracks = [t for t in self.project.tracks if t.kind == "video"]
        if not video_tracks:
            body = f"TITLE: {title or self.project.id}\nFCM: NON-DROP FRAME\n"
            return {"count": 0, "path": None, "body": body, "fps": fps}

        def _tc(frames: int) -> str:
            return self.frames_to_tc(max(0, int(frames)))["tc"].replace(":", ":")

        # CMX uses HH:MM:SS:FF with colons — we already have that
        base = video_tracks[0]
        lines = [
            f"TITLE: {(title or self.project.id).replace(chr(10), ' ')}",
            "FCM: NON-DROP FRAME",
            "",
        ]
        event = 1
        for clip in base.clips_in_order():
            media = self.project.media_by_id(clip.media)
            reel = (media.path.split("/")[-1].split("\\")[-1])[:8].upper()
            reel = "".join(ch if ch.isalnum() else "_" for ch in reel) or "AX"
            src_in = _tc(clip.src_in)
            src_out = _tc(clip.src_out)
            rec_in = _tc(clip.start)
            rec_out = _tc(clip.end)
            lines.append(
                f"{event:03d}  {reel:8s} V     C        "
                f"{src_in} {src_out} {rec_in} {rec_out}"
            )
            if clip.name:
                lines.append(f"* FROM CLIP NAME: {clip.name}")
            else:
                lines.append(f"* FROM CLIP NAME: {media.path}")
            lines.append("")
            event += 1

        body = "\n".join(lines)
        written = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            written = str(p.resolve())
        return {
            "count": event - 1,
            "path": written,
            "body": body,
            "fps": fps,
            "track_id": base.id,
            "agent_note": "Simple CMX-style EDL of first video track only.",
        }

    def describe_clip(self, clip_id: str) -> dict[str, Any]:
        """Rich clip card: layout, media, track, fades, link group peers."""
        track, clip = self._find_clip_and_track(clip_id)
        media = self.project.media_by_id(clip.media)
        fades = self.get_clip_fades(clip_id)
        fps = float(self.project.timebase.fps or 30.0)
        peers = self.linked_group(clip_id)
        return {
            "clip": {
                "id": clip.id,
                "start": clip.start,
                "end": clip.end,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
                "speed": clip.speed,
                "muted": clip.muted,
                "name": clip.name,
                "color": clip.color,
                "position": clip.position,
                "link_group": clip.link_group,
                "transition_in": clip.transition_in,
                "effects": [dict(e) for e in (clip.effects or [])],
                "gain_db": self.get_clip_gain_db(clip_id),
                "opacity": self.get_clip_opacity(clip_id),
                "fade_in_frames": fades["fade_in_frames"],
                "fade_out_frames": fades["fade_out_frames"],
                "timeline_duration_frames": clip.timeline_duration_frames,
                "start_tc": self.frames_to_tc(clip.start)["tc"],
                "end_tc": self.frames_to_tc(clip.end)["tc"],
                "duration_seconds": round(clip.timeline_duration_frames / fps, 3),
            },
            "track": {
                "id": track.id,
                "kind": track.kind,
                "name": track.name,
                "muted": track.muted,
                "solo": track.solo,
                "locked": track.locked,
            },
            "media": {
                "id": media.id,
                "path": media.path,
                "kind": media.kind,
                "duration_frames": media.duration_frames,
                "has_audio": media.has_audio,
                "proxy_path": media.proxy_path,
                "origin": media.origin,
            },
            "linked": peers,
        }

    def search_clips(
        self,
        query: str,
        *,
        track_id: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Search clips by name, color, media path, or id substring (case-insensitive)."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty")
        q = query.strip().lower()
        hits: list[dict[str, Any]] = []
        for track in self.project.tracks:
            if track_id is not None and track.id != track_id:
                continue
            if kind is not None and track.kind != kind:
                continue
            for clip in track.clips_in_order():
                media = self.project.media_by_id(clip.media)
                hay = " ".join(
                    str(x)
                    for x in (
                        clip.id,
                        clip.name or "",
                        clip.color or "",
                        clip.link_group or "",
                        media.path,
                        media.id,
                        track.id,
                        track.name or "",
                    )
                ).lower()
                if q in hay:
                    hits.append({
                        "clip_id": clip.id,
                        "track_id": track.id,
                        "track_kind": track.kind,
                        "name": clip.name,
                        "start": clip.start,
                        "end": clip.end,
                        "media_path": media.path,
                        "link_group": clip.link_group,
                    })
        return {"query": query, "count": len(hits), "hits": hits}

    def clips_in_range(
        self,
        start_frame: int,
        end_frame: int,
        *,
        track_id: str | None = None,
        kind: str | None = None,
        partial: bool = True,
    ) -> dict[str, Any]:
        """List clips overlapping [start_frame, end_frame).

        partial=True: any overlap. partial=False: fully contained.
        """
        if not isinstance(start_frame, int) or not isinstance(end_frame, int):
            raise ValueError("start_frame and end_frame must be ints")
        if end_frame <= start_frame:
            raise ValueError("end_frame must be > start_frame")
        hits: list[dict[str, Any]] = []
        for track in self.project.tracks:
            if track_id is not None and track.id != track_id:
                continue
            if kind is not None and track.kind != kind:
                continue
            for clip in track.clips_in_order():
                if partial:
                    if clip.end <= start_frame or clip.start >= end_frame:
                        continue
                else:
                    if clip.start < start_frame or clip.end > end_frame:
                        continue
                hits.append({
                    "clip_id": clip.id,
                    "track_id": track.id,
                    "track_kind": track.kind,
                    "start": clip.start,
                    "end": clip.end,
                    "name": clip.name,
                    "media_id": clip.media,
                })
        return {
            "start_frame": start_frame,
            "end_frame": end_frame,
            "partial": partial,
            "count": len(hits),
            "clips": hits,
        }

    def fit_to_fill(
        self,
        clip_id: str,
        end_frame: int | None = None,
        *,
        clamp: bool = True,
    ) -> dict[str, Any]:
        """Rate-stretch a clip so its end meets end_frame (or the next clip's start).

        Does not move neighbors. end_frame=None uses the start of the next clip
        on the same track; if this is the last clip, raises ValueError.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            if end_frame is None:
                ordered = track.clips_in_order()
                nxt = None
                for c in ordered:
                    if c.start > clip.start:
                        nxt = c
                        break
                if nxt is None:
                    raise ValueError(
                        "fit_to_fill needs end_frame when clip is last on track"
                    )
                end_frame = nxt.start
            if not isinstance(end_frame, int):
                raise ValueError("end_frame must be an int")
            target = end_frame - clip.start
            if target <= 0:
                raise ValueError(
                    f"end_frame {end_frame} must be after clip.start {clip.start}"
                )
            # Reuse stretch_to math without nested _mutate
            src_len = clip.duration_frames
            if src_len <= 0:
                raise ValueError("clip has empty source range")
            raw_speed = src_len / float(target)
            speed = raw_speed
            clamped = False
            if clamp:
                if speed < 0.25:
                    speed = 0.25
                    clamped = True
                elif speed > 4.0:
                    speed = 4.0
                    clamped = True
            else:
                if speed < 0.25 or speed > 4.0:
                    raise ValueError(
                        f"required speed {raw_speed:.4f} outside [0.25, 4.0]"
                    )
            old_speed = clip.speed
            old_end = clip.end
            clip.speed = float(speed)
            return {
                "clip_id": clip_id,
                "end_frame": end_frame,
                "speed": {"from": old_speed, "to": clip.speed},
                "end": {"from": old_end, "to": clip.end},
                "duration_frames": clip.timeline_duration_frames,
                "raw_speed": round(raw_speed, 6),
                "clamped": clamped,
                "agent_note": "Neighbors not moved. Overlap with next clip is rejected on export.",
            }

    def replace_edit(
        self,
        clip_id: str,
        media_id: str,
        *,
        mode: str = "stretch",
    ) -> dict[str, Any]:
        """Replace a clip's media while keeping timeline start (and duration when possible).

        mode:
          - stretch: full new media, rate-stretch to previous timeline duration
          - trim_end: use new media from 0 for previous duration (at 1×; clamp)
          - trim_start: use tail of new media for previous duration
          - full: full new media at 1× (timeline footprint may change)
        """
        if mode not in ("stretch", "trim_end", "trim_start", "full"):
            raise ValueError(
                "mode must be stretch|trim_end|trim_start|full"
            )
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            new_media = self.project.media_by_id(media_id)
            if track.kind == "video" and new_media.kind == "audio":
                raise ValueError("cannot replace video-track clip with audio media")
            if track.kind == "audio" and new_media.kind == "image":
                raise ValueError("cannot replace audio-track clip with image media")
            old = {
                "media": clip.media,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
                "speed": clip.speed,
                "end": clip.end,
            }
            target_dur = clip.timeline_duration_frames
            max_out = max(1, new_media.duration_frames)
            clip.media = new_media.id
            if mode == "full":
                clip.src_in = 0
                clip.src_out = max_out
                clip.speed = 1.0
            elif mode == "trim_end":
                clip.speed = 1.0
                clip.src_in = 0
                clip.src_out = min(max_out, max(1, target_dur))
            elif mode == "trim_start":
                clip.speed = 1.0
                take = min(max_out, max(1, target_dur))
                clip.src_out = max_out
                clip.src_in = max(0, max_out - take)
            else:  # stretch
                clip.src_in = 0
                clip.src_out = max_out
                if target_dur <= 0:
                    clip.speed = 1.0
                else:
                    speed = max_out / float(target_dur)
                    if speed < 0.25:
                        speed = 0.25
                    elif speed > 4.0:
                        speed = 4.0
                    clip.speed = float(speed)
            return {
                "clip_id": clip_id,
                "mode": mode,
                "media_id": new_media.id,
                "from": old,
                "to": {
                    "media": clip.media,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "speed": clip.speed,
                    "end": clip.end,
                },
                "track_id": track.id,
                "agent_note": "Timeline start unchanged. stretch keeps prior duration when possible.",
            }

    def copy_to_track(
        self,
        clip_id: str,
        track_id: str,
        *,
        start: int | None = None,
        copy_effects: bool = True,
        copy_link: bool = False,
    ) -> dict[str, Any]:
        """Clone a clip onto another same-kind track (new clip id).

        start=None keeps the same timeline start. Does not remove the source.
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            src_track, clip = self._find_clip_and_track(clip_id)
            dest = self.project.track_by_id(track_id)
            if dest.locked:
                raise ValueError(f"track {dest.id} is locked")
            if dest.kind != src_track.kind:
                raise ValueError(
                    f"track kind mismatch: source {src_track.kind} vs dest {dest.kind}"
                )
            place_at = clip.start if start is None else int(start)
            if place_at < 0:
                raise ValueError("start must be >= 0")
            media = self.project.media_by_id(clip.media)
            nc = self.project.add_clip(
                dest, media, place_at, clip.src_in, clip.src_out,
            )
            nc.speed = clip.speed
            if copy_effects:
                nc.effects = [dict(e) for e in (clip.effects or [])]
            if clip.position:
                nc.position = dict(clip.position)
            nc.muted = bool(clip.muted)
            nc.name = clip.name
            nc.color = clip.color
            if copy_link and clip.link_group:
                nc.link_group = clip.link_group
            if clip.transition_in:
                nc.transition_in = dict(clip.transition_in)
            return {
                "from_clip_id": clip_id,
                "clip_id": nc.id,
                "track_id": dest.id,
                "start": nc.start,
                "end": nc.end,
                "agent_note": "Source clip unchanged. Check overlaps on dest track.",
            }

    def rename_clips(
        self,
        pattern: str,
        clip_ids: list[str] | None = None,
        *,
        track_id: str | None = None,
    ) -> dict[str, Any]:
        """Batch-rename clips. Tokens: {n} {nn} {name} {media} {id} {track}.

        clip_ids=None renames all (optionally filtered by track_id), ordered
        by track order then start. {n}=1-based index, {nn}=zero-padded 2-digit.
        """
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be non-empty")
        with self._mutate():
            targets: list[tuple[Any, Any]] = []  # (track, clip)
            if clip_ids is not None:
                for cid in dict.fromkeys(clip_ids):
                    tr, cl = self._find_clip_and_track(cid)
                    if track_id is not None and tr.id != track_id:
                        continue
                    if tr.locked:
                        raise ValueError(f"track {tr.id} is locked")
                    targets.append((tr, cl))
            else:
                for tr in self.project.tracks:
                    if track_id is not None and tr.id != track_id:
                        continue
                    if tr.locked:
                        continue
                    for cl in tr.clips_in_order():
                        targets.append((tr, cl))
            renamed: list[dict[str, Any]] = []
            for i, (tr, cl) in enumerate(targets, start=1):
                media = self.project.media_by_id(cl.media)
                base = Path(media.path).stem if media.path else media.id
                old = cl.name
                name = (
                    pattern
                    .replace("{nn}", f"{i:02d}")
                    .replace("{n}", str(i))
                    .replace("{name}", old or base)
                    .replace("{media}", base)
                    .replace("{id}", cl.id)
                    .replace("{track}", tr.name or tr.id)
                )
                cl.name = name
                renamed.append({
                    "clip_id": cl.id,
                    "from": old,
                    "to": name,
                })
            return {
                "pattern": pattern,
                "count": len(renamed),
                "renamed": renamed,
            }

    def import_edl(
        self,
        text: str | None = None,
        *,
        path: str | Path | None = None,
        track_id: str | None = None,
        replace_track: bool = False,
        media_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Import a simple CMX-style EDL (pair of export_edl).

        Matches reel names to project media by basename stem (or media_map
        reel→media_id). Places events on the first video track (or track_id).
        replace_track=True clears that track first.
        """
        if text is None and path is None:
            raise ValueError("pass text= or path=")
        if text is None:
            text = Path(path).read_text(encoding="utf-8")
        assert text is not None
        # Event line: 001  REELNAME V     C        src_in src_out rec_in rec_out
        import re
        event_re = re.compile(
            r"^\s*(\d+)\s+(\S+)\s+V\s+C\s+"
            r"(\d{1,2}:\d{2}:\d{2}:\d{2})\s+"
            r"(\d{1,2}:\d{2}:\d{2}:\d{2})\s+"
            r"(\d{1,2}:\d{2}:\d{2}:\d{2})\s+"
            r"(\d{1,2}:\d{2}:\d{2}:\d{2})\s*$",
            re.IGNORECASE,
        )
        name_re = re.compile(r"^\s*\*\s*FROM CLIP NAME:\s*(.+)\s*$", re.IGNORECASE)
        events: list[dict[str, Any]] = []
        pending_name: str | None = None
        # Collect in reverse association: name lines follow event
        raw_events: list[dict[str, Any]] = []
        for line in text.splitlines():
            m = event_re.match(line)
            if m:
                raw_events.append({
                    "event": int(m.group(1)),
                    "reel": m.group(2),
                    "src_in_tc": m.group(3),
                    "src_out_tc": m.group(4),
                    "rec_in_tc": m.group(5),
                    "rec_out_tc": m.group(6),
                    "clip_name": None,
                })
                continue
            nm = name_re.match(line)
            if nm and raw_events:
                raw_events[-1]["clip_name"] = nm.group(1).strip()

        # Same reel recipe as export_edl (basename[:8] alnum/underscore).
        def _reel_key(s: str) -> str:
            base = (s or "").split("/")[-1].split("\\")[-1]
            key = "".join(ch if ch.isalnum() else "_" for ch in base[:8]).upper()
            return key or "AX"

        media_by_reel: dict[str, Any] = {}
        for media in self.project.media:
            base = (media.path or "").split("/")[-1].split("\\")[-1]
            media_by_reel.setdefault(_reel_key(base), media)
            # stem-only fallback for human reels
            stem = Path(base).stem.upper()
            media_by_reel.setdefault(
                "".join(ch if ch.isalnum() else "_" for ch in stem)[:8] or "AX",
                media,
            )
        if media_map:
            for reel, mid in media_map.items():
                media_by_reel[_reel_key(reel)] = self.project.media_by_id(mid)
                media_by_reel[str(reel).upper()[:8]] = self.project.media_by_id(mid)

        with self._mutate():
            if track_id is None:
                vtracks = [t for t in self.project.tracks if t.kind == "video"]
                if not vtracks:
                    track = self.project.add_track("video")
                else:
                    track = vtracks[0]
            else:
                track = self.project.track_by_id(track_id)
                if track.kind != "video":
                    raise ValueError("import_edl places on a video track")
            if track.locked:
                raise ValueError(f"track {track.id} is locked")
            if replace_track:
                track.clips.clear()

            placed: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for ev in raw_events:
                reel_k = _reel_key(ev["reel"])
                media = media_by_reel.get(reel_k)
                if media is None:
                    # try clip name path stem
                    cn = ev.get("clip_name") or ""
                    media = media_by_reel.get(_reel_key(cn))
                if media is None:
                    skipped.append({**ev, "reason": "no media match for reel"})
                    continue
                src_in = int(self.tc_to_frames(ev["src_in_tc"])["frame"])
                src_out = int(self.tc_to_frames(ev["src_out_tc"])["frame"])
                rec_in = int(self.tc_to_frames(ev["rec_in_tc"])["frame"])
                rec_out = int(self.tc_to_frames(ev["rec_out_tc"])["frame"])
                if src_out <= src_in:
                    skipped.append({**ev, "reason": "empty source range"})
                    continue
                max_out = max(1, media.duration_frames)
                src_in = max(0, min(src_in, max_out - 1))
                src_out = max(src_in + 1, min(src_out, max_out))
                # Prefer record duration when source was rate-stretched on export
                rec_dur = max(1, rec_out - rec_in)
                clip = self.project.add_clip(
                    track, media, rec_in, src_in, src_out,
                )
                src_len = clip.duration_frames
                if src_len > 0 and rec_dur != src_len:
                    speed = src_len / float(rec_dur)
                    if 0.25 <= speed <= 4.0:
                        clip.speed = float(speed)
                if ev.get("clip_name"):
                    # Prefer basename if path-like
                    cn = ev["clip_name"]
                    clip.name = Path(cn).name if ("/" in cn or "\\" in cn) else cn
                placed.append({
                    "event": ev["event"],
                    "clip_id": clip.id,
                    "media_id": media.id,
                    "start": clip.start,
                    "end": clip.end,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                })
            return {
                "track_id": track.id,
                "placed": placed,
                "count": len(placed),
                "skipped": skipped,
                "skipped_count": len(skipped),
                "replace_track": replace_track,
                "agent_note": "Simple CMX import; media must already be in the project bin.",
            }

    def lift(
        self,
        start_frame: int,
        end_frame: int,
        *,
        track_id: str | None = None,
        track_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Lift [start, end) leaving a gap (extract_time with ripple=False).

        track_id / track_ids / kind filter which tracks; default = all tracks.
        One undo for multi-track.
        """
        if end_frame <= start_frame:
            raise ValueError("end_frame must be > start_frame")
        with self._mutate():
            if track_ids is not None:
                targets = [self.project.track_by_id(t) for t in track_ids]
            elif track_id is not None:
                targets = [self.project.track_by_id(track_id)]
            else:
                targets = list(self.project.tracks)
                if kind is not None:
                    targets = [t for t in targets if t.kind == kind]
            results: list[dict[str, Any]] = []
            for tr in targets:
                if tr.locked:
                    continue
                results.append(
                    self._extract_time_unlocked(
                        tr.id, start_frame, end_frame, ripple=False,
                    )
                )
            return {
                "start_frame": start_frame,
                "end_frame": end_frame,
                "ripple": False,
                "tracks": results,
                "count": len(results),
                "agent_note": "Gap left open; fill_track_gaps or insert later.",
            }

    def split_at_markers(
        self,
        *,
        track_ids: list[str] | None = None,
        marker_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Razor all (or selected) tracks at each marker frame. One undo."""
        markers = list(self.project.markers)
        if marker_ids is not None:
            wanted = set(marker_ids)
            markers = [m for m in markers if m.id in wanted]
        frames = sorted({int(m.frame) for m in markers})
        if not frames:
            return {
                "frames": [],
                "splits": [],
                "count": 0,
                "agent_note": "No markers — nothing to split.",
            }
        with self._mutate():
            all_splits: list[dict[str, Any]] = []
            for fr in frames:
                tracks = self.project.tracks
                if track_ids is not None:
                    wanted_t = set(track_ids)
                    tracks = [t for t in tracks if t.id in wanted_t]
                for track in tracks:
                    if track.locked:
                        continue
                    for clip in list(track.clips_in_order()):
                        if clip.start < fr < clip.end:
                            left, right = self._split_clip_unlocked(clip.id, fr)
                            all_splits.append({
                                "frame": fr,
                                "track_id": track.id,
                                "left_id": left.id,
                                "right_id": right.id,
                            })
            return {
                "frames": frames,
                "splits": all_splits,
                "count": len(all_splits),
                "agent_note": "One undo undoes all marker razors.",
            }

    def match_duration(
        self,
        clip_id: str,
        reference_clip_id: str,
        *,
        clamp: bool = True,
    ) -> dict[str, Any]:
        """Rate-stretch clip_id so its timeline duration matches reference."""
        ref = self._find_clip(reference_clip_id)
        return self.stretch_to(
            clip_id, ref.timeline_duration_frames, clamp=clamp,
        )

    def set_clips_color(
        self,
        clip_ids: list[str],
        color: str | None,
    ) -> dict[str, Any]:
        """Set or clear color chip on many clips (one undo). color=None clears."""
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        with self._mutate():
            out: list[dict[str, Any]] = []
            for cid in dict.fromkeys(clip_ids):
                self._assert_clip_track_unlocked(cid)
                clip = self._find_clip(cid)
                if color is None or (isinstance(color, str) and not color.strip()):
                    clip.color = None
                else:
                    clip.color = str(color).strip()
                out.append({"clip_id": cid, "color": clip.color})
            return {"count": len(out), "clips": out}

    def clips_by_color(
        self,
        color: str,
        *,
        track_id: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Find clips whose color chip matches (case-insensitive)."""
        if not isinstance(color, str) or not color.strip():
            raise ValueError("color must be non-empty")
        q = color.strip().lower()
        hits: list[dict[str, Any]] = []
        for track in self.project.tracks:
            if track_id is not None and track.id != track_id:
                continue
            if kind is not None and track.kind != kind:
                continue
            for clip in track.clips_in_order():
                if (clip.color or "").strip().lower() == q:
                    hits.append({
                        "clip_id": clip.id,
                        "track_id": track.id,
                        "start": clip.start,
                        "end": clip.end,
                        "name": clip.name,
                        "color": clip.color,
                    })
        return {"color": color, "count": len(hits), "clips": hits}

    def export_cutlist(
        self,
        path: str | Path | None = None,
        *,
        format: str = "csv",
        track_id: str | None = None,
    ) -> dict[str, Any]:
        """Export a simple cut list (csv or json) of clips in timeline order.

        Columns: event, track, kind, name, start_tc, end_tc, start_f, end_f,
        src_in, src_out, speed, media, color.
        """
        if format not in ("csv", "json"):
            raise ValueError("format must be csv|json")
        rows: list[dict[str, Any]] = []
        event = 1
        tracks = self.project.tracks
        if track_id is not None:
            tracks = [self.project.track_by_id(track_id)]
        for track in tracks:
            for clip in track.clips_in_order():
                media = self.project.media_by_id(clip.media)
                rows.append({
                    "event": event,
                    "track_id": track.id,
                    "track_name": track.name or "",
                    "kind": track.kind,
                    "clip_id": clip.id,
                    "name": clip.name or "",
                    "start_tc": self.frames_to_tc(clip.start)["tc"],
                    "end_tc": self.frames_to_tc(clip.end)["tc"],
                    "start_f": clip.start,
                    "end_f": clip.end,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "speed": clip.speed,
                    "media": media.path,
                    "media_id": media.id,
                    "color": clip.color or "",
                    "muted": bool(clip.muted),
                })
                event += 1
        if format == "json":
            body = json.dumps(rows, indent=2, ensure_ascii=False)
        else:
            headers = [
                "event", "track_id", "track_name", "kind", "clip_id", "name",
                "start_tc", "end_tc", "start_f", "end_f", "src_in", "src_out",
                "speed", "media", "media_id", "color", "muted",
            ]
            lines = [",".join(headers)]
            for r in rows:
                cells = []
                for h in headers:
                    v = r.get(h, "")
                    s = str(v)
                    if any(c in s for c in ",\"\n"):
                        s = '"' + s.replace('"', '""') + '"'
                    cells.append(s)
                lines.append(",".join(cells))
            body = "\n".join(lines) + ("\n" if lines else "")
        written = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            written = str(p.resolve())
        return {
            "format": format,
            "count": len(rows),
            "path": written,
            "body": body,
            "rows": rows if format == "json" else None,
            "agent_note": "Cut list is read-only report; not an interchange graph.",
        }

    def place_media(
        self,
        media_id: str,
        track_id: str,
        start: int,
        *,
        src_in: int | None = None,
        src_out: int | None = None,
        mode: str = "insert",
        name: str | None = None,
    ) -> dict[str, Any]:
        """Place project media on a track (three-point style).

        mode=insert: place only. mode=overwrite: lift range first (no ripple).
        """
        if mode not in ("insert", "overwrite"):
            raise ValueError("mode must be insert|overwrite")
        if not isinstance(start, int) or start < 0:
            raise ValueError("start must be >= 0")
        with self._mutate():
            track = self.project.track_by_id(track_id)
            if track.locked:
                raise ValueError(f"track {track.id} is locked")
            media = self.project.media_by_id(media_id)
            if track.kind == "video" and media.kind == "audio":
                raise ValueError("cannot place audio media on video track")
            if track.kind == "audio" and media.kind == "image":
                raise ValueError("cannot place image media on audio track")
            sin = 0 if src_in is None else int(src_in)
            sout = media.duration_frames if src_out is None else int(src_out)
            if sin < 0 or sout <= sin:
                raise ValueError("invalid src_in/src_out")
            if sout > media.duration_frames:
                raise ValueError("src_out exceeds media duration")
            # temporary clip math for duration
            dur = sout - sin  # at 1x
            if mode == "overwrite":
                self._extract_time_unlocked(
                    track_id, start, start + dur, ripple=False,
                )
            clip = self.project.add_clip(track, media, start, sin, sout)
            if name:
                clip.name = str(name).strip() or None
            return {
                "clip_id": clip.id,
                "track_id": track.id,
                "media_id": media.id,
                "start": clip.start,
                "end": clip.end,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
                "mode": mode,
            }

    def join_clips(
        self,
        clip_id_a: str,
        clip_id_b: str,
    ) -> dict[str, Any]:
        """Merge two adjacent clips on the same track into one.

        Requirements: same track, same media, same speed, hard-cut adjacent
        (b.start == a.end), and contiguous source (b.src_in == a.src_out) when
        speed==1; for speed!=1 source must still abut. Keeps a's effects/meta.
        """
        with self._mutate():
            ta, a = self._find_clip_and_track(clip_id_a)
            tb, b = self._find_clip_and_track(clip_id_b)
            if ta.id != tb.id:
                raise ValueError("clips must be on the same track")
            if ta.locked:
                raise ValueError(f"track {ta.id} is locked")
            # Order left→right
            if a.start > b.start:
                a, b = b, a
                clip_id_a, clip_id_b = clip_id_b, clip_id_a
            if b.start != a.end:
                raise ValueError(
                    f"clips not adjacent: {a.id} ends {a.end}, {b.id} starts {b.start}"
                )
            if a.media != b.media:
                raise ValueError("join requires same media id")
            if abs(float(a.speed) - float(b.speed)) > 1e-9:
                raise ValueError("join requires same speed")
            if b.src_in != a.src_out:
                raise ValueError(
                    f"source not contiguous: a.src_out={a.src_out} b.src_in={b.src_in}"
                )
            if b.transition_in is not None:
                raise ValueError("cannot join across a transition_in; remove it first")
            old_b = b.id
            a.src_out = b.src_out
            # Prefer name from a; if empty take b
            if not a.name and b.name:
                a.name = b.name
            ta.clips.remove(b)
            return {
                "clip_id": a.id,
                "removed_clip_id": old_b,
                "track_id": ta.id,
                "src_in": a.src_in,
                "src_out": a.src_out,
                "start": a.start,
                "end": a.end,
                "agent_note": "Effects/meta from left clip kept.",
            }

    def set_clips_speed(
        self,
        clip_ids: list[str],
        speed: float,
    ) -> dict[str, Any]:
        """Set playback speed on many clips (one undo). Range [0.25, 4]."""
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        if not isinstance(speed, (int, float)) or float(speed) < 0.25 or float(speed) > 4.0:
            raise ValueError("speed must be in [0.25, 4.0]")
        with self._mutate():
            out: list[dict[str, Any]] = []
            for cid in dict.fromkeys(clip_ids):
                self._assert_clip_track_unlocked(cid)
                clip = self._find_clip(cid)
                old = clip.speed
                clip.speed = float(speed)
                out.append({
                    "clip_id": cid,
                    "speed": {"from": old, "to": clip.speed},
                    "end": clip.end,
                })
            return {"speed": float(speed), "count": len(out), "clips": out}

    def trim_to_range(
        self,
        clip_id: str,
        start_frame: int,
        end_frame: int,
        *,
        mode: str = "normal",
    ) -> dict[str, Any]:
        """Trim clip so it occupies [start_frame, end_frame) on the timeline.

        Adjusts src_in/src_out (and start) using speed. mode=ripple closes the
        hole left of the new start / pulls right after new end on that track.
        Does not rate-stretch — pure source trim.
        """
        if mode not in ("normal", "ripple"):
            raise ValueError("mode must be normal|ripple")
        if not isinstance(start_frame, int) or not isinstance(end_frame, int):
            raise ValueError("start_frame and end_frame must be ints")
        if end_frame <= start_frame:
            raise ValueError("end_frame must be > start_frame")
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            if not (clip.start <= start_frame < end_frame <= clip.end):
                raise ValueError(
                    f"range [{start_frame},{end_frame}) must lie inside clip "
                    f"[{clip.start},{clip.end})"
                )
            old = {
                "start": clip.start,
                "end": clip.end,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
            }
            old_start, old_end = clip.start, clip.end

            def _src_at(tl: int) -> int:
                local = tl - old_start
                if clip.speed != 1.0:
                    return clip.src_in + int(round(local * clip.speed))
                return clip.src_in + local

            new_in = max(clip.src_in, min(_src_at(start_frame), clip.src_out - 1))
            new_out = max(new_in + 1, min(_src_at(end_frame), clip.src_out))
            clip.src_in = new_in
            clip.src_out = new_out
            if mode == "normal":
                clip.start = start_frame
            else:
                # Keep left edge at old_start; pull later clips by net shrink
                clip.start = old_start
                new_dur = clip.timeline_duration_frames
                pull = (old_end - old_start) - new_dur
                if pull > 0:
                    for c in track.clips_in_order():
                        if c.id != clip.id and c.start >= old_end:
                            c.start = max(0, c.start - pull)
                            if c.transition_in is not None:
                                c.transition_in = None
            return {
                "clip_id": clip_id,
                "mode": mode,
                "from": old,
                "to": {
                    "start": clip.start,
                    "end": clip.end,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                },
                "agent_note": "Source trim only (no speed change). Use stretch_to to rate-fit.",
            }

    def auto_link_av(
        self,
        *,
        tolerance_frames: int = 0,
        track_id_video: str | None = None,
        track_id_audio: str | None = None,
    ) -> dict[str, Any]:
        """Link video+audio clips that share the same start (within tolerance).

        Pairs each unlinked video clip with an unlinked audio clip at the same
        start. Creates new link_groups. One undo.
        """
        if not isinstance(tolerance_frames, int) or tolerance_frames < 0:
            raise ValueError("tolerance_frames must be >= 0")
        with self._mutate():
            vtracks = [t for t in self.project.tracks if t.kind == "video"]
            atracks = [t for t in self.project.tracks if t.kind == "audio"]
            if track_id_video:
                vtracks = [self.project.track_by_id(track_id_video)]
            if track_id_audio:
                atracks = [self.project.track_by_id(track_id_audio)]
            videos = [
                c for t in vtracks for c in t.clips_in_order()
                if not c.link_group
            ]
            audios = [
                c for t in atracks for c in t.clips_in_order()
                if not c.link_group
            ]
            used_a: set[str] = set()
            pairs: list[dict[str, Any]] = []
            for vc in videos:
                match = None
                for ac in audios:
                    if ac.id in used_a:
                        continue
                    if abs(ac.start - vc.start) <= tolerance_frames:
                        match = ac
                        break
                if match is None:
                    continue
                gid = new_id("lnk")
                vc.link_group = gid
                match.link_group = gid
                used_a.add(match.id)
                pairs.append({
                    "link_group": gid,
                    "video_clip_id": vc.id,
                    "audio_clip_id": match.id,
                    "start_video": vc.start,
                    "start_audio": match.start,
                })
            return {
                "pairs": pairs,
                "count": len(pairs),
                "tolerance_frames": tolerance_frames,
                "agent_note": "Only unlinked clips; first audio match wins per video.",
            }

    def set_clips_meta(
        self,
        clip_ids: list[str],
        *,
        name: str | None = None,
        color: str | None = None,
        clear_name: bool = False,
        clear_color: bool = False,
    ) -> dict[str, Any]:
        """Batch set_clip_meta (one undo)."""
        if not clip_ids:
            raise ValueError("clip_ids is empty")
        with self._mutate():
            out: list[dict[str, Any]] = []
            for cid in dict.fromkeys(clip_ids):
                self._assert_clip_track_unlocked(cid)
                clip = self._find_clip(cid)
                if clear_name:
                    clip.name = None
                elif name is not None:
                    clip.name = str(name).strip() or None
                if clear_color:
                    clip.color = None
                elif color is not None:
                    clip.color = str(color).strip() or None
                out.append({
                    "clip_id": cid,
                    "name": clip.name,
                    "color": clip.color,
                })
            return {"count": len(out), "clips": out}

    def copy_attributes(self, clip_id: str) -> dict[str, Any]:
        """Copy speed/position/gain/fades/opacity into session attributes clipboard.

        Does not copy grade/effects list (use copy_effects for that).
        """
        clip = self._find_clip(clip_id)
        fades = self.get_clip_fades(clip_id)
        self._attributes_clipboard = {
            "speed": clip.speed,
            "position": dict(clip.position) if clip.position else None,
            "gain_db": self.get_clip_gain_db(clip_id),
            "opacity": self.get_clip_opacity(clip_id),
            "fade_in_frames": fades["fade_in_frames"],
            "fade_out_frames": fades["fade_out_frames"],
            "source_clip_id": clip_id,
        }
        return {
            "copied": True,
            "clip_id": clip_id,
            "attributes": dict(self._attributes_clipboard),
            "agent_note": "Session attributes clipboard — paste_attributes.",
        }

    def paste_attributes(
        self,
        clip_id: str,
        *,
        speed: bool = True,
        position: bool = True,
        gain: bool = True,
        opacity: bool = True,
        fades: bool = True,
    ) -> dict[str, Any]:
        """Paste attributes clipboard fields onto a clip (one undo)."""
        if not self._attributes_clipboard:
            raise ValueError("attributes clipboard empty — copy_attributes first")
        bp = self._attributes_clipboard
        self._assert_clip_track_unlocked(clip_id)
        applied: list[str] = []
        with self._mutate():
            clip = self._find_clip(clip_id)
            if speed and isinstance(bp.get("speed"), (int, float)):
                sp = float(bp["speed"])
                if 0.25 <= sp <= 4.0:
                    clip.speed = sp
                    applied.append("speed")
            if position:
                if bp.get("position") is None:
                    clip.position = None
                else:
                    clip.position = dict(bp["position"])
                applied.append("position")
            if gain and isinstance(bp.get("gain_db"), (int, float)):
                # inline gain set without nested mutate
                db = float(bp["gain_db"])
                clip.effects = [e for e in (clip.effects or []) if e.get("type") != "gain"]
                if abs(db) >= 0.05:
                    clip.effects.append({"type": "gain", "db": db})
                applied.append("gain")
            if opacity and isinstance(bp.get("opacity"), (int, float)):
                amount = float(bp["opacity"])
                clip.effects = [e for e in (clip.effects or []) if e.get("type") != "opacity"]
                if amount < 0.999:
                    clip.effects.append({"type": "opacity", "amount": amount})
                applied.append("opacity")
            if fades:
                fin = int(bp.get("fade_in_frames") or 0)
                fout = int(bp.get("fade_out_frames") or 0)
                # reuse fade set logic inline
                kept = [e for e in (clip.effects or []) if e.get("type") != "fade"]
                src_len = clip.duration_frames
                if fin + fout > src_len and src_len > 0:
                    # scale down proportionally
                    scale = src_len / float(fin + fout)
                    fin = int(fin * scale)
                    fout = max(0, src_len - fin)
                if fin > 0:
                    kept.append({
                        "type": "fade", "direction": "in", "duration_frames": fin,
                    })
                if fout > 0:
                    kept.append({
                        "type": "fade", "direction": "out", "duration_frames": fout,
                    })
                clip.effects = kept
                applied.append("fades")
            return {
                "clip_id": clip_id,
                "applied": applied,
                "from_clip_id": bp.get("source_clip_id"),
            }

    def clips_at(
        self,
        timeline_frame: int,
        *,
        track_id: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Hit-test: clips covering an absolute timeline frame (end exclusive)."""
        if not isinstance(timeline_frame, int):
            raise ValueError("timeline_frame must be an int")
        f = int(timeline_frame)
        hits: list[dict[str, Any]] = []
        for track in self.project.tracks:
            if track_id is not None and track.id != track_id:
                continue
            if kind is not None and track.kind != kind:
                continue
            for clip in track.clips_in_order():
                if clip.start <= f < clip.end:
                    hits.append({
                        "clip_id": clip.id,
                        "track_id": track.id,
                        "track_kind": track.kind,
                        "start": clip.start,
                        "end": clip.end,
                        "media_id": clip.media,
                        "src_in": clip.src_in,
                        "src_out": clip.src_out,
                        "name": clip.name,
                    })
        return {
            "timeline_frame": f,
            "hits": hits,
            "count": len(hits),
        }

    def match_frame(
        self,
        *,
        timeline_frame: int | None = None,
        clip_id: str | None = None,
    ) -> dict[str, Any]:
        """Map a timeline position to source media frame (NLE Match Frame).

        If clip_id given, frame defaults to mid-clip. If only timeline_frame,
        picks the topmost video hit, else first hit at that frame.
        """
        clip = None
        track = None
        if clip_id is not None:
            track, clip = self._find_clip_and_track(clip_id)
            if timeline_frame is None:
                timeline_frame = clip.start + max(0, clip.timeline_duration_frames // 2)
            if not (clip.start <= int(timeline_frame) < clip.end):
                raise ValueError("timeline_frame must be inside the clip")
        else:
            if timeline_frame is None:
                raise ValueError("timeline_frame or clip_id required")
            hits = self.clips_at(int(timeline_frame))["hits"]
            if not hits:
                raise ValueError(f"no clip at frame {timeline_frame}")
            pick = next((h for h in hits if h["track_kind"] == "video"), hits[0])
            track, clip = self._find_clip_and_track(pick["clip_id"])

        assert clip is not None and track is not None
        f = int(timeline_frame)
        local = f - clip.start
        if clip.speed != 1.0:
            src_frame = clip.src_in + int(round(local * clip.speed))
        else:
            src_frame = clip.src_in + local
        src_frame = min(max(src_frame, clip.src_in), max(clip.src_in, clip.src_out - 1))
        media = self.project.media_by_id(clip.media)
        src_t = self.project.timebase.frames_to_seconds(src_frame)
        abs_path = str(self.bundle.media_path(media.path))
        proxy_abs = None
        if media.proxy_path:
            p = self.bundle.root / media.proxy_path
            if p.exists():
                proxy_abs = str(p)
        return {
            "clip_id": clip.id,
            "track_id": track.id,
            "track_kind": track.kind,
            "timeline_frame": f,
            "media_id": media.id,
            "media_kind": media.kind,
            "path": media.path,
            "abs_path": abs_path,
            "proxy_path": media.proxy_path,
            "proxy_abs_path": proxy_abs,
            "src_frame": src_frame,
            "src_time_seconds": round(src_t, 4),
            "src_in": clip.src_in,
            "src_out": clip.src_out,
            "agent_note": (
                "Source frame for this timeline position. Use media_thumbnail / "
                "frame_at / bin scrub — does not mutate the timeline."
            ),
        }

    def set_clip_fades(
        self,
        clip_id: str,
        *,
        fade_in_frames: int = 0,
        fade_out_frames: int = 0,
    ) -> dict[str, Any]:
        """Set clip fade-in / fade-out (replaces existing fade effects). One undo.

        Uses the validated ``fade`` effect (video fade + afade on export).
        Zero frames removes that direction. Sum must not exceed source length.
        """
        if not isinstance(fade_in_frames, int) or fade_in_frames < 0:
            raise ValueError("fade_in_frames must be a non-negative int")
        if not isinstance(fade_out_frames, int) or fade_out_frames < 0:
            raise ValueError("fade_out_frames must be a non-negative int")
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            src_len = clip.duration_frames
            if fade_in_frames + fade_out_frames > src_len:
                raise ValueError(
                    f"fade_in ({fade_in_frames}) + fade_out ({fade_out_frames}) "
                    f"exceeds source duration ({src_len})"
                )
            kept = [e for e in (clip.effects or []) if e.get("type") != "fade"]
            if fade_in_frames > 0:
                kept.append({
                    "type": "fade",
                    "direction": "in",
                    "duration_frames": fade_in_frames,
                })
            if fade_out_frames > 0:
                kept.append({
                    "type": "fade",
                    "direction": "out",
                    "duration_frames": fade_out_frames,
                })
            clip.effects = kept
            return {
                "clip_id": clip_id,
                "fade_in_frames": fade_in_frames,
                "fade_out_frames": fade_out_frames,
                "agent_note": "Fade effects applied; re-export proxy to see in scrub.",
            }

    def get_clip_fades(self, clip_id: str) -> dict[str, Any]:
        """Read fade-in / fade-out frame counts from clip effects."""
        clip = self._find_clip(clip_id)
        fin = 0
        fout = 0
        for e in clip.effects or []:
            if e.get("type") != "fade":
                continue
            d = e.get("duration_frames")
            if not isinstance(d, int):
                continue
            if e.get("direction") == "in":
                fin = d
            elif e.get("direction") == "out":
                fout = d
        return {
            "clip_id": clip_id,
            "fade_in_frames": fin,
            "fade_out_frames": fout,
        }

    def relink_clip(
        self,
        clip_id: str,
        media_id: str,
        *,
        keep_source_range: bool = True,
    ) -> dict[str, Any]:
        """Point a clip at different project media (relink / replace source).

        keep_source_range=True: keep src_in/src_out when they fit the new media;
        otherwise clamp src_out to new duration (and src_in if needed).
        keep_source_range=False: use full new media (0 → duration).
        """
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            new_media = self.project.media_by_id(media_id)
            # Kind compatibility: video track clips need video/image; audio needs audio
            if track.kind == "video" and new_media.kind == "audio":
                raise ValueError("cannot relink video-track clip to audio media")
            if track.kind == "audio" and new_media.kind == "image":
                raise ValueError("cannot relink audio-track clip to image media")
            old = {
                "media": clip.media,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
            }
            if not keep_source_range:
                clip.media = new_media.id
                clip.src_in = 0
                clip.src_out = max(1, new_media.duration_frames)
            else:
                clip.media = new_media.id
                max_out = max(1, new_media.duration_frames)
                if clip.src_out > max_out:
                    clip.src_out = max_out
                if clip.src_in >= clip.src_out:
                    clip.src_in = 0
                    if clip.src_out <= 0:
                        clip.src_out = max_out
            return {
                "clip_id": clip_id,
                "media_id": new_media.id,
                "from": old,
                "to": {
                    "media": clip.media,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                },
                "track_id": track.id,
                "agent_note": "Clip retargeted; re-export proxy. Timeline start unchanged.",
            }

    def clear_position(self, clip_id: str) -> Clip:
        """Restore a clip to full-frame (remove a previously set position)."""
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            clip.position = None
            return clip

    def set_clip_rotate(self, clip_id: str, degrees: float) -> dict[str, Any]:
        """Set rotate effect (replaces existing rotate). degrees=0 removes it."""
        self._assert_clip_track_unlocked(clip_id)
        if not isinstance(degrees, (int, float)):
            raise ValueError("degrees must be numeric")
        degrees = float(degrees)
        with self._mutate():
            clip = self._find_clip(clip_id)
            old = 0.0
            for e in clip.effects or []:
                if e.get("type") == "rotate" and isinstance(e.get("degrees"), (int, float)):
                    old = float(e["degrees"])
            clip.effects = [e for e in (clip.effects or []) if e.get("type") != "rotate"]
            if abs(degrees) > 1e-6:
                self._apply_effect_unlocked(
                    clip_id, {"type": "rotate", "degrees": degrees},
                )
            return {
                "clip_id": clip_id,
                "degrees": {"from": old, "to": degrees if abs(degrees) > 1e-6 else 0.0},
            }

    def reset_clip_transform(
        self,
        clip_id: str,
        *,
        position: bool = True,
        crop: bool = True,
        rotate: bool = True,
        opacity: bool = True,
    ) -> dict[str, Any]:
        """Clear layout/transform FX: PiP position, crop, rotate, opacity.

        Does not touch grade/look effects (color, curves, lut, gain, …).
        """
        self._assert_clip_track_unlocked(clip_id)
        drop: set[str] = set()
        if crop:
            drop.add("crop")
        if rotate:
            drop.add("rotate")
        if opacity:
            drop.add("opacity")
        with self._mutate():
            clip = self._find_clip(clip_id)
            cleared: list[str] = []
            if position and clip.position is not None:
                clip.position = None
                cleared.append("position")
            if drop:
                before = list(clip.effects or [])
                clip.effects = [e for e in before if e.get("type") not in drop]
                for e in before:
                    t = e.get("type")
                    if t in drop and t not in cleared:
                        cleared.append(str(t))
            return {
                "clip_id": clip_id,
                "cleared": cleared,
                "remaining_effects": len(clip.effects or []),
            }

    def swap_clips(self, clip_a: str, clip_b: str) -> dict[str, Any]:
        """Swap two clips' timeline start times (same or different tracks).

        Source ranges, effects, and track membership stay; only ``start``
        swaps. Tracks must be unlocked.
        """
        with self._mutate():
            ta, a = self._find_clip_and_track(clip_a)
            tb, b = self._find_clip_and_track(clip_b)
            if ta.locked or tb.locked:
                raise ValueError("cannot swap clips on a locked track")
            if a.id == b.id:
                raise ValueError("clip_a and clip_b must be different")
            sa, sb = a.start, b.start
            a.start = sb
            b.start = sa
            return {
                "a": {"clip_id": a.id, "track_id": ta.id, "start": {"from": sa, "to": a.start}},
                "b": {"clip_id": b.id, "track_id": tb.id, "start": {"from": sb, "to": b.start}},
                "agent_note": "Starts swapped; check overlaps on freeform tracks.",
            }

    def move_track(
        self,
        track_id: str,
        *,
        index: int | None = None,
        delta: int | None = None,
    ) -> dict[str, Any]:
        """Reorder tracks (video z-order: later list index = higher overlay).

        Provide index (absolute 0-based) or delta (+1 = later / on top).
        """
        if (index is None) == (delta is None):
            raise ValueError("provide exactly one of index or delta")
        with self._mutate():
            tracks = self.project.tracks
            ids = [t.id for t in tracks]
            if track_id not in ids:
                raise KeyError(f"no track with id {track_id!r}")
            old_i = ids.index(track_id)
            if index is not None:
                new_i = int(index)
            else:
                new_i = old_i + int(delta)  # type: ignore[arg-type]
            new_i = max(0, min(len(tracks) - 1, new_i))
            if new_i == old_i:
                return {
                    "track_id": track_id,
                    "index": {"from": old_i, "to": new_i},
                    "unchanged": True,
                    "order": [t.id for t in tracks],
                }
            track = tracks.pop(old_i)
            tracks.insert(new_i, track)
            return {
                "track_id": track_id,
                "index": {"from": old_i, "to": new_i},
                "order": [t.id for t in tracks],
                "agent_note": "Video overlay z-order follows track list order after base.",
            }

    def set_track_name(self, track_id: str, name: str | None) -> dict[str, Any]:
        """Set optional track display name (UI only)."""
        with self._mutate():
            track = self.project.track_by_id(track_id)
            old = track.name
            track.name = (str(name).strip() or None) if name is not None else None
            return {
                "track_id": track_id,
                "name": {"from": old, "to": track.name},
            }

    def set_ducking(
        self,
        track_id: str,
        against_track_id: str,
        threshold_db: float = -30.0,
        ratio: float = 8.0,
        attack_ms: float = 20.0,
        release_ms: float = 300.0,
        makeup_db: float = 0.0,
    ) -> Track:
        """Duck ``track_id`` under ``against_track_id``: whenever the against-
        track's signal exceeds threshold_db, this track's level is compressed
        by ratio (music-under-voiceover being the classic case). A track-level
        relationship, not a clip effect — see model.Track.duck. The against
        track's own audio is untouched; it only *keys* the compression.

        Defaults are tuned for speech over music: threshold low enough that
        normal speech triggers it, ratio high enough to be clearly audible,
        release slow enough not to pump between words.
        """
        with self._mutate():
            track = self.project.track_by_id(track_id)
            against = self.project.track_by_id(against_track_id)
            if track.kind != "audio" or against.kind != "audio":
                raise ValueError(
                    "set_ducking needs two audio tracks; got "
                    f"{track_id}={track.kind!r}, {against_track_id}={against.kind!r}"
                )
            if track_id == against_track_id:
                raise ValueError("a track cannot duck against itself")
            if not isinstance(ratio, (int, float)) or not (1.0 <= ratio <= 20.0):
                raise ValueError("set_ducking 'ratio' must be in [1, 20]")
            for name, value in (
                ("threshold_db", threshold_db), ("attack_ms", attack_ms),
                ("release_ms", release_ms), ("makeup_db", makeup_db),
            ):
                if not isinstance(value, (int, float)):
                    raise ValueError(f"set_ducking {name!r} must be numeric")
            track.duck = {
                "against": against_track_id,
                "threshold_db": float(threshold_db),
                "ratio": float(ratio),
                "attack_ms": float(attack_ms),
                "release_ms": float(release_ms),
                "makeup_db": float(makeup_db),
            }
            return track

    def clear_ducking(self, track_id: str) -> Track:
        """Remove a previously-set duck relationship from a track."""
        with self._mutate():
            track = self.project.track_by_id(track_id)
            if track.duck is None:
                raise ValueError(f"track {track_id} has no ducking to clear")
            track.duck = None
            return track

    # --- generation (ARCHITECTURE.md section 8: async job model) ----------
    def _require_generation_provider(self) -> GenerationProvider:
        if self.generation_provider is None:
            raise RuntimeError(
                "no generation_provider configured on this Editor — pass one "
                "to Editor.create()/open() (e.g. ComfyUIProvider) to use generate()"
            )
        return self.generation_provider

    def generate(self, kind: str, prompt: str, params: dict | None = None) -> str:
        """Submit an async generation job; returns a job id immediately.

        Does not mutate the project — a job only enters the timeline once
        place_generated() imports its finished result.
        """
        return self._require_generation_provider().submit(kind, prompt, params or {})

    def job_status(self, job_id: str) -> GenerationJob:
        return self._require_generation_provider().status(job_id)

    def place_generated(
        self, job_id: str, track_id: str, start: int, duration_frames: int | None = None
    ) -> Clip:
        """Import a finished job's result as Media (origin records provider/
        job/prompt) and place it as a Clip. Raises if the job isn't DONE yet
        — call job_status() first rather than assuming it finished.

        duration_frames is optional for video/speech/sfx/music: leave it out
        to use the media's full real (ffprobed) duration - the natural
        choice, since you rarely know a generated clip's exact length in
        advance (found the hard way: guessing wrong for a TTS clip whose
        spoken length wasn't known ahead of generation raised a confusing
        "clip out exceeds media duration" error at add_clip time instead).
        Images have no intrinsic duration, so it's still required for those.
        """
        job = self._require_generation_provider().status(job_id)
        if job.status != JobStatus.DONE:
            raise ValueError(f"job {job_id} is not done yet (status={job.status.value})")
        if duration_frames is not None and duration_frames <= 0:
            raise ValueError(f"duration_frames must be positive, got {duration_frames}")
        # job.kind is the *generation* vocabulary (what was requested - e.g.
        # "speech"); Media.kind is the *file* vocabulary (what it actually
        # is on disk - "audio"). They coincide for image/video but not for
        # speech/sfx/music, which are all just audio files once generated.
        # kind="upscale" is special: image drafts finish as stills, video
        # drafts finish as .mp4 from the frame pipeline — decide by suffix
        # rather than inventing a second generation kind.
        media_kind = _GENERATION_KIND_TO_MEDIA_KIND.get(job.kind, job.kind)
        if (
            job.kind == "upscale"
            and job.result_path is not None
            and job.result_path.suffix.lower() in _VIDEO_UPSCALE_SUFFIXES
        ):
            media_kind = "video"
        with self._mutate():
            track = self.project.track_by_id(track_id)
            media = _ffmpeg_import_media(
                self.bundle, self.project, job.result_path, kind=media_kind,
                origin={
                    "provider": self.generation_provider.name, "job": job_id, "prompt": job.prompt,
                    "license": job.license.to_dict() if job.license else None,
                },
            )
            if duration_frames is None:
                if media_kind == "image":
                    raise ValueError("duration_frames is required for kind='image' (images have no intrinsic duration)")
                duration_frames = media.duration_frames
            return self.project.add_clip(track, media, start, 0, duration_frames)

    def get_license_report(self) -> dict[str, Any]:
        """Audit generated media in this project for licenses that restrict
        commercial use — JH's ask: quality-first model choice is fine, but
        anything not clearly commercial-safe must be visible before export/
        sale, not discovered after the fact. Metadata only, sourced from
        place_generated()/Media.origin["license"]; never touches the
        generated content itself.
        """
        entries = []
        for m in self.project.media:
            lic = (m.origin or {}).get("license")
            if lic:
                entries.append({"media_id": m.id, "path": m.path, **lic})
        flagged = [e for e in entries if e["commercial_use"] != "yes"]
        return {
            "entries": entries,
            "safe_for_commercial_use": len(flagged) == 0,
            "flagged": flagged,
        }

    def quality_check(self, path: str | Path) -> dict[str, Any]:
        """Free, deterministic checks (black/frozen/blurry/silent — see
        render.quality_check) a media file can pass before anything gets an
        agent's expensive attention (ARCHITECTURE.md 5.10's agent-director
        loop). Works on any file path, most usefully a generation job's
        result_path (from job_status) before place_generated commits it to
        the timeline — catch a "static frame passed off as motion" failure
        for free, not after it's already imported.
        """
        return _quality_check(Path(path)).to_dict()

    def analyze_audio(
        self,
        path: str | Path,
        image_path: str | Path | None = None,
        silence_threshold_db: float = -40.0,
        min_silence_seconds: float = 0.5,
    ) -> dict[str, Any]:
        """The agent's cheap "ears", pairing make_contact_sheet's eyes
        (ARCHITECTURE.md 5.10): meter any audio file — mean/max volume,
        integrated LUFS, loudness range, true peak, silence regions — and
        optionally write a waveform+spectrogram image to actually look at
        the sound's shape. Use it on generated audio before placing it, and
        on exports to check the mix (e.g. did ducking actually make room
        for the voiceover). Plain ffmpeg analysis; no model call.
        """
        return _analyze_audio(
            Path(path),
            Path(image_path) if image_path is not None else None,
            silence_threshold_db=silence_threshold_db,
            min_silence_seconds=min_silence_seconds,
        )

    def analyze_timeline(
        self,
        image_path: str | Path | None = None,
        silence_threshold_db: float = -40.0,
        min_silence_seconds: float = 0.5,
    ) -> dict[str, Any]:
        """Meter the *current project mix* (dogfood friction fix).

        ``analyze_audio`` only takes a file path — it cannot see the live
        timeline. This exports to a temp file, runs the same meters (and
        optional waveform plot), then deletes the temp. Heavier than
        analyzing a single stem, but the only honest way to answer "did
        ducking make room for the VO?" before a final export path is chosen.
        """
        import os
        import tempfile
        import time

        # mkstemp leaves the handle open — close it before ffmpeg writes, or
        # export fails / Windows keeps a lock that survives analyze_audio.
        fd, raw = tempfile.mkstemp(prefix="opmiere_mix_", suffix=".mp4")
        os.close(fd)
        tmp = Path(raw)
        try:
            self.export(tmp)
            result = self.analyze_audio(
                tmp,
                image_path=image_path,
                silence_threshold_db=silence_threshold_db,
                min_silence_seconds=min_silence_seconds,
            )
            result["source"] = "timeline_export"
            result["timeline_frames"] = self.duration_frames()
            return result
        finally:
            # Windows: antivirus/indexer may hold the file briefly after ffmpeg
            # exits — retry unlink rather than raise and lose a good result.
            for _ in range(5):
                try:
                    tmp.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.1)

    def make_contact_sheet(
        self, path: str | Path, output_path: str | Path, cols: int = 3, rows: int = 3
    ) -> str:
        """Tile cols*rows evenly-spaced thumbnails from a video into one
        small grid image at output_path — the agent's cheap "eyes" for
        judging a shot's motion/composition (ARCHITECTURE.md 5.10), without
        the token cost of sending full-res frames or many separate images.
        Read the returned path to actually look at it.
        """
        return str(_make_contact_sheet(Path(path), Path(output_path), cols=cols, rows=rows))

    def make_sequence_contact_sheet(
        self,
        output_path: str | Path,
        *,
        max_tiles: int = 12,
        tile_width: int = 160,
        tile_height: int = 90,
        cols: int | None = None,
    ) -> dict[str, Any]:
        """Grid of mid-frames from each base-track clip — whole-cut eyes."""
        return _make_sequence_contact_sheet(
            self.project,
            self.bundle,
            Path(output_path),
            max_tiles=max_tiles,
            tile_width=tile_width,
            tile_height=tile_height,
            cols=cols,
        )

    def review_cut(
        self,
        *,
        min_clip_seconds: float = 0.4,
        max_brightness_jump: float = 45.0,
        check_brightness_jumps: bool = True,
        expect_music_duck: bool = True,
    ) -> dict[str, Any]:
        """Structural craft review of the live timeline (gaps, flash cuts, ducking)."""
        return _review_cut(
            self.project,
            self.bundle,
            min_clip_seconds=min_clip_seconds,
            max_brightness_jump=max_brightness_jump,
            check_brightness_jumps=check_brightness_jumps,
            expect_music_duck=expect_music_duck,
        )

    def normalize_loudness(
        self,
        path: str | Path,
        output_path: str | Path,
        *,
        preset: str = "streaming",
        target_lufs: float | None = None,
        true_peak: float | None = None,
        lra: float | None = None,
        two_pass: bool = True,
    ) -> dict[str, Any]:
        """Loudness-normalize a media file (export or stem) to a platform target."""
        return _normalize_loudness(
            Path(path),
            Path(output_path),
            preset=preset,
            target_lufs=target_lufs,
            true_peak=true_peak,
            lra=lra,
            two_pass=two_pass,
        )

    def delivery_check(
        self,
        path: str | Path,
        *,
        preset: str = "streaming",
        target_lufs: float | None = None,
        true_peak_limit: float | None = None,
        lufs_tolerance: float = 1.5,
        expected_width: int | None = None,
        expected_height: int | None = None,
        expected_fps: float | None = None,
        expected_duration_seconds: float | None = None,
        duration_tolerance_seconds: float = 0.35,
        run_quality_check: bool = True,
        match_project: bool = True,
    ) -> dict[str, Any]:
        """Gate a finished export: LUFS/true-peak, geometry, quality_check.

        When match_project=True (default), expected width/height/fps default
        from the open project if not passed explicitly.
        """
        w = expected_width
        h = expected_height
        fps = expected_fps
        if match_project:
            if w is None:
                w = self.project.resolution.w
            if h is None:
                h = self.project.resolution.h
            if fps is None:
                fps = self.project.timebase.fps
        return _delivery_check(
            Path(path),
            preset=preset,
            target_lufs=target_lufs,
            true_peak_limit=true_peak_limit,
            lufs_tolerance=lufs_tolerance,
            expected_width=w,
            expected_height=h,
            expected_fps=fps,
            expected_duration_seconds=expected_duration_seconds,
            duration_tolerance_seconds=duration_tolerance_seconds,
            run_quality_check=run_quality_check,
        )

    def transcribe(
        self,
        path: str | Path,
        *,
        model_size: str = "base",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        word_timestamps: bool = True,
    ) -> dict[str, Any]:
        """Speech-to-text on a media file (faster-whisper). Returns segments
        with start/end/text (+ words when word_timestamps). Does not mutate
        the project — pair with write_srt + apply_effect subtitles, or use
        caption_clip for the one-shot path.
        """
        return _transcribe(
            Path(path),
            model_size=model_size,
            language=language,
            device=device,
            compute_type=compute_type,
            word_timestamps=word_timestamps,
        )

    def write_srt(self, path: str | Path, segments: list[dict[str, Any]]) -> str:
        """Write segments (from transcribe) to an .srt file. Returns path."""
        return str(_write_srt(Path(path), segments))

    def suggest_silence_cuts(
        self,
        path: str | Path,
        *,
        silence_threshold_db: float = -40.0,
        min_silence_seconds: float = 0.4,
        pad_seconds: float = 0.08,
        min_keep_seconds: float = 0.2,
    ) -> dict[str, Any]:
        """Suggest keep_ranges between silences (ffmpeg silencedetect).

        Agent uses these to trim/split dead air — does not edit the timeline
        automatically.
        """
        return _suggest_keep_ranges(
            Path(path),
            silence_threshold_db=silence_threshold_db,
            min_silence_seconds=min_silence_seconds,
            pad_seconds=pad_seconds,
            min_keep_seconds=min_keep_seconds,
        )

    def cache_transcript(
        self,
        media_id: str,
        transcript: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a transcript dict under analysis/transcripts/{media_id}.json."""
        self.project.media_by_id(media_id)  # validate
        path = _save_transcript(self.bundle.analysis_dir, media_id, transcript)
        return {
            "media_id": media_id,
            "path": str(path),
            "segments": len(transcript.get("segments") or []),
        }

    def load_cached_transcript(self, media_id: str) -> dict[str, Any] | None:
        self.project.media_by_id(media_id)
        return _load_transcript(self.bundle.analysis_dir, media_id)

    def transcribe_media(
        self,
        media_id: str,
        *,
        model_size: str = "base",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        word_timestamps: bool = True,
        cache: bool = True,
    ) -> dict[str, Any]:
        """Transcribe a registered media asset and optionally cache the result."""
        media = self.project.media_by_id(media_id)
        path = self.bundle.media_path(media.path)
        result = _transcribe(
            path,
            model_size=model_size,
            language=language,
            device=device,
            compute_type=compute_type,
            word_timestamps=word_timestamps,
        )
        result["media_id"] = media_id
        if cache:
            cached = self.cache_transcript(media_id, result)
            result["cache_path"] = cached["path"]
        return result

    def search_transcripts(
        self,
        query: str,
        *,
        media_id: str | None = None,
        segments: list[dict[str, Any]] | None = None,
        max_hits: int = 20,
    ) -> dict[str, Any]:
        """Keyword search over cached transcripts or an explicit segments list.

        Pass media_id to search one asset cache; omit to search all caches.
        Pass segments to search an in-memory transcript without cache.
        """
        if segments is not None:
            return _search_segments(query, segments, max_hits=max_hits)

        if media_id is not None:
            tr = _load_transcript(self.bundle.analysis_dir, media_id)
            if tr is None:
                return {
                    "query": query,
                    "media_id": media_id,
                    "hits": [],
                    "hit_count": 0,
                    "error": "no cached transcript — run transcribe_media first",
                }
            return _search_transcript_dict(query, tr, max_hits=max_hits)

        all_hits: list[dict[str, Any]] = []
        searched: list[str] = []
        for m in self.project.media:
            tr = _load_transcript(self.bundle.analysis_dir, m.id)
            if tr is None:
                continue
            searched.append(m.id)
            part = _search_transcript_dict(query, tr, max_hits=max_hits)
            for h in part.get("hits") or []:
                h = dict(h)
                h["media_id"] = m.id
                all_hits.append(h)
        all_hits.sort(key=lambda h: (-float(h.get("score", 0)), float(h.get("start", 0))))
        all_hits = all_hits[: max(1, int(max_hits))]
        return {
            "query": query,
            "searched_media_ids": searched,
            "hits": all_hits,
            "hit_count": len(all_hits),
            "agent_note": (
                "Keyword ranking across cached transcripts. "
                "Cache via transcribe_media / cache_transcript."
            ),
        }

    def suggest_filler_cuts(
        self,
        *,
        path: str | Path | None = None,
        clip_id: str | None = None,
        media_id: str | None = None,
        segments: list[dict[str, Any]] | None = None,
        extra_words: list[str] | None = None,
        pad_seconds: float = 0.02,
        model_size: str = "base",
        language: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Suggest cut/keep ranges for um/uh/那个/就是… from word-level ASR.

        Provide segments, or path/clip_id/media_id to load/transcribe.
        Does not edit the timeline — use apply_keep_ranges or apply_filler_cuts.
        """
        resolved_media_id = media_id
        src_path: Path | None = Path(path) if path else None
        duration: float | None = None

        if clip_id is not None:
            clip = self._find_clip(clip_id)
            media = self.project.media_by_id(clip.media)
            resolved_media_id = media.id
            src_path = self.bundle.media_path(media.path)
            duration = self.project.timebase.frames_to_seconds(media.duration_frames)

        if segments is None:
            if resolved_media_id and use_cache:
                cached = _load_transcript(self.bundle.analysis_dir, resolved_media_id)
                if cached and cached.get("segments"):
                    segments = list(cached["segments"])
                    duration = duration or float(cached.get("duration_seconds") or 0) or None
            if segments is None:
                if src_path is None and resolved_media_id:
                    media = self.project.media_by_id(resolved_media_id)
                    src_path = self.bundle.media_path(media.path)
                if src_path is None:
                    raise ValueError(
                        "provide segments, path, clip_id, or media_id with audio"
                    )
                tr = _transcribe(
                    src_path,
                    model_size=model_size,
                    language=language,
                    word_timestamps=True,
                )
                segments = list(tr.get("segments") or [])
                duration = float(tr.get("duration_seconds") or 0) or duration
                if resolved_media_id and use_cache:
                    tr["media_id"] = resolved_media_id
                    self.cache_transcript(resolved_media_id, tr)

        plan = _suggest_filler_cuts(
            segments or [],
            duration_seconds=duration,
            extra_words=extra_words,
            pad_seconds=pad_seconds,
        )
        if clip_id is not None:
            plan["clip_id"] = clip_id
        if resolved_media_id:
            plan["media_id"] = resolved_media_id
        if src_path is not None:
            plan["path"] = str(src_path)
        return plan

    def apply_keep_ranges(
        self,
        clip_id: str,
        keep_ranges: list[dict[str, Any]],
        *,
        time_unit: str = "seconds",
    ) -> dict[str, Any]:
        """Replace one clip with contiguous pieces covering only keep_ranges.

        keep_ranges use media source time (seconds default, or frames).
        Intersected with the clip's current [src_in, src_out). Packed left from
        the original timeline start. Followers after the clip keep relative gaps.
        Single undo step.
        """
        if time_unit not in ("seconds", "frames"):
            raise ValueError("time_unit must be 'seconds' or 'frames'")
        if not keep_ranges:
            raise ValueError(
                "keep_ranges is empty — refusing to delete entire clip silently"
            )

        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            if clip.speed != 1.0:
                raise ValueError("apply_keep_ranges requires speed=1.0")
            media = self.project.media_by_id(clip.media)
            fps = float(self.project.timebase.fps or 30.0)

            def to_frames(start: float, end: float) -> tuple[int, int]:
                if time_unit == "frames":
                    return int(start), int(end)
                return (
                    int(round(float(start) * fps)),
                    int(round(float(end) * fps)),
                )

            windows: list[tuple[int, int]] = []
            for r in keep_ranges:
                s, e = to_frames(r["start"], r["end"])
                s = max(s, clip.src_in)
                e = min(e, clip.src_out)
                if e > s:
                    windows.append((s, e))
            windows.sort()
            merged: list[tuple[int, int]] = []
            for s, e in windows:
                if not merged or s > merged[-1][1]:
                    merged.append((s, e))
                else:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            if not merged:
                raise ValueError(
                    "no keep_ranges intersect the clip source window "
                    f"[{clip.src_in}, {clip.src_out})"
                )

            old_start = clip.start
            old_end = clip.end
            old_id = clip.id
            # Preserve gap from original clip end to each later clip
            followers = [
                (c, c.start - old_end)
                for c in track.clips_in_order()
                if c.id != clip.id and c.start >= old_end
            ]
            track.clips.remove(clip)

            new_ids: list[str] = []
            cursor = old_start
            for s, e in merged:
                new_c = self.project.add_clip(track, media, cursor, s, e)
                new_ids.append(new_c.id)
                cursor = new_c.end
            new_len = cursor - old_start

            for c, offset in followers:
                c.start = cursor + max(0, int(offset))

            return {
                "removed_clip_id": old_id,
                "track_id": track.id,
                "new_clip_ids": new_ids,
                "keep_windows_frames": [
                    {"src_in": s, "src_out": e} for s, e in merged
                ],
                "timeline_start": old_start,
                "timeline_duration_frames": new_len,
                "followers_shifted": [c.id for c, _ in followers],
                "agent_note": (
                    "Original clip replaced by keep pieces; single undo restores all."
                ),
            }

    def apply_filler_cuts(
        self,
        clip_id: str,
        *,
        dry_run: bool = True,
        extra_words: list[str] | None = None,
        pad_seconds: float = 0.02,
        model_size: str = "base",
        language: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """One-shot filler 粗剪: plan from ASR, optionally apply_keep_ranges.

        dry_run=True (default) only returns the plan — set dry_run=False to cut.
        """
        plan = self.suggest_filler_cuts(
            clip_id=clip_id,
            extra_words=extra_words,
            pad_seconds=pad_seconds,
            model_size=model_size,
            language=language,
            use_cache=use_cache,
        )
        if dry_run:
            plan["applied"] = False
            plan["agent_note"] = (
                (plan.get("agent_note") or "")
                + " dry_run=true — re-call with dry_run=false to apply."
            )
            return plan
        if not plan.get("keep_ranges"):
            plan["applied"] = False
            plan["error"] = "no keep_ranges (nothing left after cuts?)"
            return plan
        applied = self.apply_keep_ranges(
            clip_id, plan["keep_ranges"], time_unit="seconds",
        )
        return {**plan, "applied": True, "result": applied}

    def detect_scenes(
        self,
        path: str | Path,
        *,
        threshold: float = 27.0,
        min_scene_len: int = 15,
        backend: str = "auto",
    ) -> dict[str, Any]:
        """Detect shot boundaries in a video (PySceneDetect or ffmpeg fallback)."""
        return _detect_scenes(
            Path(path),
            threshold=threshold,
            min_scene_len=min_scene_len,
            backend=backend,
        )

    def suggest_project_fps(
        self,
        paths: list[str] | None = None,
        preference: str = "auto",
    ) -> dict[str, Any]:
        """Recommend timeline fps: 24/25/30/50/60 from sources (max 60)."""
        return _suggest_project_fps(paths, preference=preference)

    def suggest_project_resolution(
        self,
        paths: list[str] | None = None,
        preference: str = "auto",
    ) -> dict[str, Any]:
        """Recommend timeline resolution (720p–4k). errors if sources too small."""
        return _suggest_project_resolution(paths, preference=preference)

    def check_delivery_limits(
        self,
        paths: list[str] | None = None,
        *,
        fps: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Gate: can we honestly claim this fps/resolution from these sources?"""
        return _check_delivery_limits(paths=paths, fps=fps, width=width, height=height)

    def plan_edit(
        self,
        cards: list[dict[str, Any]] | None = None,
        paths: list[str] | None = None,
        *,
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
    ) -> dict[str, Any]:
        """Build EDL from asset cards/paths. Does not mutate the project."""
        return _plan_edit(
            cards=cards,
            paths=paths,
            fps=float(fps if fps is not None else self.project.timebase.fps),
            width=width if width is not None else self.project.resolution.w,
            height=height if height is not None else self.project.resolution.h,
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

    def apply_edit_plan(
        self,
        plan: dict[str, Any],
        *,
        track_ids: dict[str, str] | None = None,
        skip_missing: bool = False,
    ) -> dict[str, Any]:
        """Apply a plan_edit EDL onto the open project (import + place + transitions).

        ``track_ids`` maps track_hint → existing track id. Missing hints create
        tracks: video_base first video, video_overlay later video, audio_* on
        audio tracks in order.
        """
        if not isinstance(plan, dict) or "events" not in plan:
            raise ValueError("plan must be a plan_edit result with 'events'")
        events = plan.get("events") or []
        if not isinstance(events, list):
            raise ValueError("plan.events must be a list")

        hint_to_id: dict[str, str] = dict(track_ids or {})
        placed: list[dict[str, Any]] = []
        errors: list[str] = []
        media_by_path: dict[str, str] = {}
        last_clip_on: dict[str, str] = {}

        def _ensure_track(hint: str) -> str:
            if hint in hint_to_id:
                return hint_to_id[hint]
            kind: TrackKind = "video" if hint.startswith("video") else "audio"
            if hint in ("video_base", "audio_music") or hint.endswith("_base"):
                existing = [t for t in self.project.tracks if t.kind == kind]
                used = set(hint_to_id.values())
                for t in existing:
                    if t.id not in used:
                        hint_to_id[hint] = t.id
                        return t.id
            trk = self.add_track(kind)
            hint_to_id[hint] = trk.id
            return trk.id

        import os
        import subprocess
        import tempfile

        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                errors.append(f"events[{i}]: skip non-dict")
                continue
            op = ev.get("op")
            if op not in ("place", "place_black"):
                errors.append(f"events[{i}]: skip op {op!r}")
                continue

            kind = ev.get("kind") or "video"
            if kind not in ("video", "audio", "image"):
                kind = "video"
            hint = str(
                ev.get("track_hint")
                or ("video_base" if kind != "audio" else "audio_music")
            )
            track_id = _ensure_track(hint)

            try:
                if op == "place_black":
                    dur_s = float(
                        ev.get("src_out_seconds")
                        or (int(ev.get("src_out_frames") or 1) / self.project.timebase.fps)
                    )
                    dur_s = max(0.05, dur_s)
                    w, h = self.project.resolution.w, self.project.resolution.h
                    fps = self.project.timebase.fps
                    fd, raw = tempfile.mkstemp(prefix="opmiere_jcut_", suffix=".mp4")
                    os.close(fd)
                    slug_path = Path(raw)
                    proc = subprocess.run(
                        [
                            "ffmpeg", "-y", "-f", "lavfi",
                            "-i", f"color=c=black:s={w}x{h}:d={dur_s}:r={fps}",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            str(slug_path),
                        ],
                        capture_output=True, text=True,
                    )
                    if proc.returncode != 0 or not slug_path.exists():
                        raise RuntimeError(
                            f"place_black failed:\n{(proc.stderr or '')[-1200:]}"
                        )
                    path = str(slug_path)
                    kind = "video"
                else:
                    path = ev.get("path")
                    if not path or not Path(path).exists():
                        msg = f"events[{i}]: missing file {path!r}"
                        if skip_missing:
                            errors.append(msg)
                            continue
                        raise FileNotFoundError(msg)

                if path not in media_by_path:
                    media = self.import_media(Path(path), kind)  # type: ignore[arg-type]
                    media_by_path[path] = media.id
                media_id = media_by_path[path]
                media_obj = self.project.media_by_id(media_id)

                src_in = int(ev.get("src_in_frames") or 0)
                src_out = ev.get("src_out_frames")
                if src_out is None:
                    src_out = media_obj.duration_frames
                else:
                    src_out = int(src_out)
                if media_obj.duration_frames and src_out > media_obj.duration_frames:
                    src_out = media_obj.duration_frames
                if src_out <= src_in:
                    errors.append(f"events[{i}]: empty range after clamp")
                    continue

                abs_start = ev.get("timeline_start_frames")
                if abs_start is None and ev.get("timeline_start_seconds") is not None:
                    abs_start = self.project.timebase.seconds_to_frames(
                        float(ev["timeline_start_seconds"])
                    )

                prev_id = last_clip_on.get(track_id)
                if abs_start is not None:
                    clip = self.add_clip(
                        track_id, media_id, int(abs_start), src_in, src_out,
                    )
                elif prev_id is None:
                    track = self.project.track_by_id(track_id)
                    ordered = track.clips_in_order()
                    start = ordered[-1].end if ordered else 0
                    clip = self.add_clip(track_id, media_id, start, src_in, src_out)
                else:
                    clip = self.place_after(
                        prev_id, media_id, src_in=src_in, src_out=src_out,
                    )

                t_in = ev.get("transition_in")
                if (
                    t_in and isinstance(t_in, dict)
                    and prev_id is not None
                    and abs_start is None
                ):
                    t_type = t_in.get("type")
                    t_frames = int(t_in.get("duration_frames") or 0)
                    if t_type and t_frames > 0 and t_type in KNOWN_TRANSITION_TYPES:
                        try:
                            clip = self.add_transition(clip.id, t_type, t_frames)
                        except ValueError as te:
                            errors.append(f"events[{i}] transition: {te}")

                for fx in ev.get("effects") or []:
                    if isinstance(fx, dict) and fx.get("type"):
                        try:
                            clip = self.apply_effect(clip.id, dict(fx))
                        except Exception as fe:
                            errors.append(f"events[{i}] effect: {fe}")

                last_clip_on[track_id] = clip.id
                placed.append({
                    "event_index": i,
                    "clip_id": clip.id,
                    "media_id": media_id,
                    "track_id": track_id,
                    "track_hint": hint,
                    "start": clip.start,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "transition_in": clip.transition_in,
                    "absolute": abs_start is not None,
                    "op": op,
                })
            except Exception as e:
                if skip_missing:
                    errors.append(f"events[{i}]: {e}")
                    continue
                raise

        return {
            "placed": placed,
            "placed_count": len(placed),
            "track_ids": hint_to_id,
            "errors": errors,
            "duration_frames": self.duration_frames(),
        }

    def detect_beats(
        self,
        path: str | Path,
        *,
        max_seconds: float | None = 180.0,
        sensitivity: float = 1.15,
    ) -> dict[str, Any]:
        """Beat/onset times from music or video audio (energy peak-pick)."""
        return _detect_beats(
            Path(path), max_seconds=max_seconds, sensitivity=sensitivity,
        )

    def suggest_mix(
        self,
        *,
        vo_path: str | Path | None = None,
        music_path: str | Path | None = None,
        sfx_path: str | Path | None = None,
        vo_track_id: str | None = None,
        music_track_id: str | None = None,
        target_vo_lufs: float = -16.0,
        target_music_lufs: float = -22.0,
    ) -> dict[str, Any]:
        """Suggest gain dB + ducking from VO/music stem meters."""
        return _suggest_mix(
            vo_path=vo_path,
            music_path=music_path,
            sfx_path=sfx_path,
            vo_track_id=vo_track_id,
            music_track_id=music_track_id,
            target_vo_lufs=target_vo_lufs,
            target_music_lufs=target_music_lufs,
        )

    def suggest_dialogue_chain(
        self,
        path: str | Path,
        *,
        has_music_bleed: bool = False,
    ) -> dict[str, Any]:
        """Recommended denoise/compress/gain steps for a VO file."""
        return _suggest_dialogue_chain(path, has_music_bleed=has_music_bleed)

    def apply_mix_plan(
        self,
        plan: dict[str, Any],
        *,
        role_clip_ids: dict[str, list[str]] | None = None,
        music_track_id: str | None = None,
        vo_track_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply a suggest_mix result: gain on clips by role + set_ducking.

        ``role_clip_ids`` maps ``vo``/``music``/``sfx`` → clip id lists.
        If omitted, gains apply to all clips on the matching track_id from
        each action (when present).
        """
        if not isinstance(plan, dict) or "actions" not in plan:
            raise ValueError("plan must be a suggest_mix result with 'actions'")
        applied: list[dict[str, Any]] = []
        errors: list[str] = []
        role_clip_ids = role_clip_ids or {}

        def _clips_for_role(role: str, track_hint: str | None) -> list[str]:
            if role in role_clip_ids and role_clip_ids[role]:
                return list(role_clip_ids[role])
            tid = track_hint
            if not tid:
                return []
            try:
                track = self.project.track_by_id(tid)
            except KeyError:
                return []
            return [c.id for c in track.clips]

        for action in plan.get("actions") or []:
            if not isinstance(action, dict):
                continue
            op = action.get("op")
            try:
                if op == "gain":
                    role = str(action.get("role") or "")
                    db = float(action["db"])
                    track_id = action.get("track_id")
                    cids = _clips_for_role(role, track_id)
                    if not cids and track_id:
                        cids = _clips_for_role(role, track_id)
                    # Fallback: all clips on first audio track matching role name
                    if not cids:
                        for t in self.project.tracks:
                            if t.kind != "audio":
                                continue
                            # heuristic: use track with clips if only one audio
                            if len([x for x in self.project.tracks if x.kind == "audio"]) == 1:
                                cids = [c.id for c in t.clips]
                                break
                    for cid in cids:
                        self.apply_effect(cid, {"type": "gain", "db": db})
                        applied.append({"op": "gain", "clip_id": cid, "db": db})
                    if not cids:
                        errors.append(f"gain {role}: no clips found — pass role_clip_ids")
                elif op == "set_ducking":
                    m_id = action.get("music_track_id") or music_track_id
                    v_id = action.get("vo_track_id") or vo_track_id
                    if not m_id or not v_id:
                        # try resolve from project: first two audio tracks
                        audio = [t for t in self.project.tracks if t.kind == "audio"]
                        if len(audio) >= 2 and not m_id:
                            m_id = audio[0].id
                        if len(audio) >= 2 and not v_id:
                            v_id = audio[1].id
                    if not m_id or not v_id:
                        errors.append("set_ducking: need music_track_id and vo_track_id")
                        continue
                    self.set_ducking(
                        m_id,
                        v_id,
                        threshold_db=float(action.get("threshold_db", -30)),
                        ratio=float(action.get("ratio", 8)),
                        attack_ms=float(action.get("attack_ms", 20)),
                        release_ms=float(action.get("release_ms", 280)),
                        makeup_db=float(action.get("makeup_db", 0)),
                    )
                    applied.append({
                        "op": "set_ducking",
                        "music_track_id": m_id,
                        "vo_track_id": v_id,
                    })
                else:
                    errors.append(f"unknown mix action {op!r}")
            except Exception as e:
                errors.append(f"{op}: {e}")

        return {
            "applied": applied,
            "applied_count": len(applied),
            "errors": errors,
        }

    def list_look_presets(self) -> dict[str, Any]:
        """Available project looks (name → effect list)."""
        return {
            "presets": {k: list(v) for k, v in _LOOK_PRESETS.items()},
            "names": sorted(_LOOK_PRESETS),
        }

    def list_style_presets(self) -> dict[str, Any]:
        """Film aesthetic styles (pacing + grade params) for agent blend."""
        return _list_styles()

    def apply_style_preset(
        self,
        styles: str | list[str],
        *,
        clip_ids: list[str] | None = None,
        video_only: bool = True,
        apply_motion: bool = True,
        place_audio_assets: bool = True,
    ) -> dict[str, Any]:
        """Apply one or more blended film styles as deterministic effects.

        Example: styles=\"ang_lee,horror\" merges pacing hints + effect stacks.
        Maps aesthetics → FFmpeg-backed params (not generative invent-a-look):
        grade, vignette, optional slow ken_burns, optional local LUT/drone paths.
        """
        if isinstance(styles, str):
            names = [s.strip() for s in styles.replace("+", ",").split(",") if s.strip()]
        else:
            names = [str(s).strip() for s in styles if str(s).strip()]
        style = _blend_styles(names)
        effects = _resolve_style_effects(style)

        # Optional LUT if file exists under style asset search path
        lut = style.get("color_lut") or (style.get("audio") or {}).get("color_lut")
        if isinstance(lut, str) and lut.strip():
            lut_path = _resolve_style_asset(
                lut.strip(), kind="lut", bundle_root=self.bundle.root,
            )
            if lut_path is not None:
                effects.append({"type": "lut3d", "path": str(lut_path)})

        # Motion: slow push for ang_lee-like camera_movement
        motion_applied = 0
        if apply_motion and style.get("camera_movement") in (
            "slow_zoom", "slow_push", "push_in",
        ):
            targets = clip_ids
            if targets is None:
                targets = [
                    c.id
                    for t in self.project.tracks if t.kind == "video"
                    for c in t.clips
                ]
            for cid in targets or []:
                try:
                    self.apply_effect(cid, {
                        "type": "ken_burns",
                        "zoom_start": 1.0,
                        "zoom_end": 1.08,
                        "x_start": 0.5,
                        "y_start": 0.5,
                        "x_end": 0.5,
                        "y_end": 0.48,
                    })
                    motion_applied += 1
                except Exception:
                    pass

        applied = self.apply_project_look(effects, clip_ids=clip_ids, video_only=video_only)

        audio_placed = None
        drone = style.get("audio_track_layer") or (style.get("audio") or {}).get(
            "audio_track_layer"
        )
        if place_audio_assets and isinstance(drone, str) and drone.strip():
            drone_path = _resolve_style_asset(
                drone.strip(), kind="audio", bundle_root=self.bundle.root,
            )
            if drone_path is not None and drone_path.exists():
                try:
                    tr = self.add_track("audio")
                    clip = self.place_from_file(drone_path, "audio", tr.id, 0)
                    g = (style.get("audio") or {}).get("music_gain_db", -12)
                    if abs(float(g)) >= 0.1:
                        self.apply_effect(clip.id, {"type": "gain", "db": float(g)})
                    audio_placed = {"track_id": tr.id, "clip_id": clip.id, "path": str(drone_path)}
                except Exception as e:
                    audio_placed = {"error": str(e)}

        return {
            "styles": names,
            "resolved": {
                k: style[k]
                for k in (
                    "label", "pace", "min_clip_seconds", "transition_preference",
                    "transition_frames", "framing_rule", "camera_movement",
                    "notes", "audio", "blend",
                )
                if k in style
            },
            "effects_applied": applied,
            "motion_clips": motion_applied,
            "audio_placed": audio_placed,
            "agent_note": (
                "Aesthetics applied as params (grade/motion/optional assets). "
                "Honor min_clip_seconds + transition_preference on plan_edit; "
                "explain blend to user in director voice; they can tweak effects on timeline."
            ),
        }

    def encode_status(self) -> dict[str, Any]:
        """Whether NVENC is usable for delivery encode."""
        return _encode_status()

    def list_style_assets(self) -> dict[str, Any]:
        """Available LUTs/audio beds on the style asset search path."""
        return _list_style_assets(self.bundle.root)

    def list_cut_templates(self) -> dict[str, Any]:
        """Named first-cut recipes (talking_head, short_form, …)."""
        return _list_cut_templates()

    def apply_cut_template(
        self,
        template: str,
        paths: list[str | Path] | None = None,
        *,
        a_roll: list[str | Path] | None = None,
        music: str | Path | None = None,
        vo: str | Path | None = None,
        style_override: str | None = None,
        dry_run: bool = False,
        build_proxy: bool = False,
        apply_silence: bool = False,
    ) -> dict[str, Any]:
        """Apply a cut template: place media, style, optional duck; return next steps.

        paths: mixed list (auto-split video vs audio) if role lists omitted.
        dry_run=True: only return the plan without mutating.
        apply_silence=True: run silence keep-ranges on first A-roll clip when
        multiple keep islands exist (safe no-op if no silence detected).
        """
        tmpl = _get_cut_template(template)
        opts = dict(tmpl.get("options") or {})
        style_name = style_override or tmpl.get("style") or "documentary"

        a_paths = [Path(p) for p in (a_roll or [])]
        music_path = Path(music) if music else None
        vo_path = Path(vo) if vo else None
        extra_audio: list[Path] = []

        for p in paths or []:
            pp = Path(p)
            kind = self.guess_media_kind(pp)
            if kind == "audio":
                if music_path is None:
                    music_path = pp
                elif vo_path is None:
                    vo_path = pp
                else:
                    extra_audio.append(pp)
            else:
                a_paths.append(pp)

        plan = {
            "template": tmpl.get("id") or template,
            "label": tmpl.get("label"),
            "style": style_name,
            "a_roll": [str(p) for p in a_paths],
            "music": str(music_path) if music_path else None,
            "vo": str(vo_path) if vo_path else None,
            "extra_audio": [str(p) for p in extra_audio],
            "options": opts,
            "next_steps": list(tmpl.get("next_steps") or []),
        }

        if dry_run:
            plan["applied"] = False
            plan["agent_note"] = "dry_run — re-call with dry_run=false to place+style."
            return plan

        if not a_paths and not music_path and not vo_path:
            raise ValueError("provide paths and/or a_roll/music/vo")

        result: dict[str, Any] = {
            **plan,
            "applied": True,
            "batch": None,
            "style_result": None,
            "duck": None,
            "hints": [],
        }

        if a_paths:
            result["batch"] = self.place_batch(
                a_paths,
                sequential=bool(opts.get("sequential_video", True)),
                build_proxy=build_proxy,
                image_duration_frames=int(opts.get("image_duration_frames", 90)),
            )

        music_track_id = None
        vo_track_id = None
        if music_path and music_path.exists():
            tr = self.add_track("audio")
            clip = self.place_from_file(music_path, "audio", tr.id, 0)
            g = opts.get("music_gain_db", -12)
            if abs(float(g)) >= 0.1:
                self.set_clip_gain(clip.id, float(g))
            music_track_id = tr.id
            result["music_clip_id"] = clip.id
            result["music_track_id"] = tr.id
        if vo_path and vo_path.exists():
            tr = self.add_track("audio")
            clip = self.place_from_file(vo_path, "audio", tr.id, 0)
            vo_track_id = tr.id
            result["vo_clip_id"] = clip.id
            result["vo_track_id"] = tr.id
        for ap in extra_audio:
            if ap.exists():
                tr = self.add_track("audio")
                self.place_from_file(ap, "audio", tr.id, 0)

        if (
            opts.get("duck_music_under_vo")
            and music_track_id
            and vo_track_id
        ):
            try:
                self.set_ducking(music_track_id, vo_track_id)
                result["duck"] = {
                    "music": music_track_id,
                    "vo": vo_track_id,
                }
            except Exception as e:
                result["duck"] = {"error": str(e)}

        # Style on video clips
        try:
            result["style_result"] = self.apply_style_preset(str(style_name))
        except Exception as e:
            result["style_result"] = {"error": str(e)}

        # Hints for silence/filler without auto-destroying timeline
        video_clips = [
            c for t in self.project.tracks if t.kind == "video" for c in t.clips
        ]
        result["silence"] = None
        if apply_silence and video_clips:
            try:
                result["silence"] = self.apply_silence_to_clip(
                    video_clips[0].id,
                    min_silence_seconds=0.35,
                    dry_run=False,
                )
                # refresh clip list after possible replace
                video_clips = [
                    c for t in self.project.tracks if t.kind == "video" for c in t.clips
                ]
            except Exception as e:
                result["silence"] = {"error": str(e)[:400]}
        if opts.get("suggest_silence") and video_clips and not apply_silence:
            result["hints"].append({
                "tool": "apply_silence_to_clip",
                "clip_id": video_clips[0].id,
                "note": "Dead-air keep_ranges; or apply_silence=True on template",
            })
        if opts.get("suggest_filler") and video_clips:
            result["hints"].append({
                "tool": "apply_filler_cuts",
                "clip_id": video_clips[0].id,
                "dry_run": True,
                "note": "Review cut_ranges before dry_run=false",
            })
        result["hints"].append({
            "tool": "finish_delivery",
            "normalize_preset": opts.get("normalize_preset", "streaming"),
        })
        result["timeline"] = self.timeline_view()
        result["agent_note"] = (
            f"Template {tmpl.get('id')} applied. Follow next_steps / hints; "
            "finish_delivery for export+delivery_check."
        )
        return result

    def apply_silence_to_clip(
        self,
        clip_id: str,
        *,
        silence_threshold_db: float = -40.0,
        min_silence_seconds: float = 0.4,
        pad_seconds: float = 0.08,
        min_keep_seconds: float = 0.2,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Suggest (and optionally apply) silence keep-ranges on one clip's media.

        dry_run=True only returns keep_ranges. apply only when ≥2 keep islands
        (otherwise a full-duration keep is a no-op / refused).
        """
        clip = self._find_clip(clip_id)
        media = self.project.media_by_id(clip.media)
        path = self.bundle.media_path(media.path)
        plan = self.suggest_silence_cuts(
            path,
            silence_threshold_db=silence_threshold_db,
            min_silence_seconds=min_silence_seconds,
            pad_seconds=pad_seconds,
            min_keep_seconds=min_keep_seconds,
        )
        keeps = list(plan.get("keep_ranges") or [])
        out: dict[str, Any] = {
            "clip_id": clip_id,
            "path": str(path),
            "keep_ranges": keeps,
            "silence_count": len(plan.get("silences") or []),
            "applied": False,
        }
        if dry_run:
            out["agent_note"] = "dry_run — re-call dry_run=false to apply_keep_ranges"
            return out
        if len(keeps) < 2:
            out["skipped"] = True
            out["agent_note"] = (
                "Need ≥2 keep islands to trim; continuous audio = no silence cut."
            )
            return out
        applied = self.apply_keep_ranges(clip_id, keeps, time_unit="seconds")
        out["applied"] = True
        out["result"] = applied
        return out

    def add_marker(
        self,
        frame: int | None = None,
        *,
        time_seconds: float | None = None,
        label: str = "",
        color: str = "#7c9cff",
    ) -> dict[str, Any]:
        """Add a timeline marker. Pass frame or time_seconds."""
        fps = float(self.project.timebase.fps or 30.0)
        if frame is None:
            if time_seconds is None:
                raise ValueError("provide frame or time_seconds")
            frame = int(round(float(time_seconds) * fps))
        with self._mutate():
            m = self.project.add_marker(int(frame), label=label, color=color)
            return {
                **m.to_dict(),
                "time_seconds": round(m.frame / fps, 3),
            }

    def delete_marker(self, marker_id: str) -> dict[str, Any]:
        with self._mutate():
            m = self.project.marker_by_id(marker_id)
            self.project.markers.remove(m)
            return {"deleted_id": marker_id}

    def update_marker(
        self,
        marker_id: str,
        *,
        label: str | None = None,
        color: str | None = None,
        frame: int | None = None,
        time_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Update marker label / color / frame (one undo)."""
        fps = float(self.project.timebase.fps or 30.0)
        if frame is None and time_seconds is not None:
            frame = int(round(float(time_seconds) * fps))
        with self._mutate():
            m = self.project.marker_by_id(marker_id)
            if label is not None:
                m.label = str(label)
            if color is not None:
                m.color = str(color)
            if frame is not None:
                if int(frame) < 0:
                    raise ValueError("marker frame must be >= 0")
                m.frame = int(frame)
                self.project.markers.sort(key=lambda x: x.frame)
            return {
                **m.to_dict(),
                "time_seconds": round(m.frame / fps, 3),
            }

    def list_markers(self) -> dict[str, Any]:
        fps = float(self.project.timebase.fps or 30.0)
        items = [
            {**m.to_dict(), "time_seconds": round(m.frame / fps, 3)}
            for m in sorted(self.project.markers, key=lambda x: x.frame)
        ]
        return {"count": len(items), "markers": items}

    def marker_near(
        self,
        frame: int,
        *,
        direction: str = "next",
        wrap: bool = False,
    ) -> dict[str, Any]:
        """Find next/prev marker relative to a timeline frame.

        direction: next | prev | nearest
        wrap: cycle at ends (for next/prev only)
        """
        if direction not in ("next", "prev", "nearest"):
            raise ValueError("direction must be next|prev|nearest")
        if not isinstance(frame, int):
            raise ValueError("frame must be an int")
        fps = float(self.project.timebase.fps or 30.0)
        markers = sorted(self.project.markers, key=lambda x: x.frame)
        if not markers:
            return {
                "found": False,
                "frame": frame,
                "direction": direction,
                "agent_note": "No markers in project.",
            }

        def _pack(m: Any) -> dict[str, Any]:
            return {
                **m.to_dict(),
                "time_seconds": round(m.frame / fps, 3),
            }

        if direction == "nearest":
            best = min(markers, key=lambda m: (abs(m.frame - frame), m.frame))
            return {
                "found": True,
                "direction": direction,
                "from_frame": frame,
                "marker": _pack(best),
                "delta_frames": best.frame - frame,
            }

        if direction == "next":
            for m in markers:
                if m.frame > frame:
                    return {
                        "found": True,
                        "direction": "next",
                        "from_frame": frame,
                        "marker": _pack(m),
                        "delta_frames": m.frame - frame,
                    }
            if wrap:
                m = markers[0]
                return {
                    "found": True,
                    "direction": "next",
                    "from_frame": frame,
                    "marker": _pack(m),
                    "delta_frames": m.frame - frame,
                    "wrapped": True,
                }
            return {"found": False, "direction": "next", "from_frame": frame}

        # prev
        for m in reversed(markers):
            if m.frame < frame:
                return {
                    "found": True,
                    "direction": "prev",
                    "from_frame": frame,
                    "marker": _pack(m),
                    "delta_frames": m.frame - frame,
                }
        if wrap:
            m = markers[-1]
            return {
                "found": True,
                "direction": "prev",
                "from_frame": frame,
                "marker": _pack(m),
                "delta_frames": m.frame - frame,
                "wrapped": True,
            }
        return {"found": False, "direction": "prev", "from_frame": frame}

    def finish_delivery(
        self,
        output_path: str | Path,
        *,
        normalize_preset: str | None = "streaming",
        delivery_preset: str = "streaming",
        run_review: bool = True,
        run_sequence_sheet: bool = False,
        sequence_sheet_path: str | Path | None = None,
        lufs_tolerance: float = 3.5,
        prepare: bool = True,
    ) -> dict[str, Any]:
        """Review (optional) + export + delivery_check in one honest finish step.

        prepare=True fills base video gaps with black pads so freeform drags export.
        Does not lie: if delivery_check ok=false, returns ok=False with details.
        """
        out: dict[str, Any] = {
            "output_path": str(output_path),
            "prepare": None,
            "review": None,
            "sequence_sheet": None,
            "export": None,
            "delivery_check": None,
            "ok": False,
        }
        if prepare:
            try:
                out["prepare"] = self.prepare_export(fill_video=True, fill_audio=False)
            except Exception as e:
                out["prepare"] = {"error": str(e)[:400]}
        if run_review:
            try:
                out["review"] = self.review_cut()
            except Exception as e:
                out["review"] = {"ok": False, "error": str(e)[:400]}
        if run_sequence_sheet:
            sp = sequence_sheet_path or (
                self.bundle.root / "review" / "sequence_sheet.png"
            )
            try:
                out["sequence_sheet"] = self.make_sequence_contact_sheet(sp)
            except Exception as e:
                out["sequence_sheet"] = {"error": str(e)[:400]}

        written = self.export(
            Path(output_path),
            normalize_preset=normalize_preset,
        )
        out["export"] = {
            "path": str(written),
            "exists": written.exists(),
            "size": written.stat().st_size if written.exists() else 0,
            "normalize_preset": normalize_preset,
        }
        dc = self.delivery_check(
            written, preset=delivery_preset, lufs_tolerance=lufs_tolerance,
        )
        out["delivery_check"] = dc
        # Hard ok: file exists + no geometry-class errors; soft on LUFS for shorts
        geo_errors = [
            e for e in (dc.get("errors") or [])
            if any(k in str(e).lower() for k in ("width", "height", "fps", "no video", "empty"))
        ]
        out["ok"] = bool(
            written.exists()
            and written.stat().st_size > 500
            and not geo_errors
        )
        out["delivery_ok"] = bool(dc.get("ok"))
        out["agent_note"] = (
            "ok=true means file+geometry gate; delivery_ok is full delivery_check. "
            "Do not claim pro delivery if delivery_ok=false without user waiver."
        )
        return out

    def apply_project_look(
        self,
        look: str | list[dict[str, Any]] = "cinematic",
        *,
        clip_ids: list[str] | None = None,
        video_only: bool = True,
    ) -> dict[str, Any]:
        """Apply one look language to many clips (default: all video clips).

        ``look`` is a preset name (cool_setup, warm_resolve, cinematic, …)
        or a list of effect dicts. Harmonizes the cut without regenerating.
        """
        effects = _resolve_look(look)
        if not effects:
            return {
                "look": look if isinstance(look, str) else "custom",
                "applied": [],
                "effect_count": 0,
                "note": "neutral look — nothing applied",
            }
        targets: list[str] = []
        if clip_ids is not None:
            targets = list(clip_ids)
        else:
            for track in self.project.tracks:
                if video_only and track.kind != "video":
                    continue
                for clip in track.clips:
                    targets.append(clip.id)

        applied: list[dict[str, Any]] = []
        for cid in targets:
            for fx in effects:
                clip = self.apply_effect(cid, dict(fx))
                applied.append({"clip_id": cid, "effect": dict(fx), "effects_len": len(clip.effects)})
        return {
            "look": look if isinstance(look, str) else "custom",
            "clip_count": len(targets),
            "effect_count": len(effects),
            "applied_count": len(applied),
            "applied": applied,
        }

    def color_match_to_clip(
        self,
        reference_clip_id: str,
        clip_ids: list[str] | None = None,
        *,
        strength: float = 0.65,
    ) -> dict[str, Any]:
        """Pull other video clips' grade toward the reference clip mid-frame.

        Measures luma/chroma via signalstats, applies color + white_balance
        deltas. Does not invent pixels — only deterministic grade shifts.
        """
        ref_track, ref_clip = self._find_clip_and_track(reference_clip_id)
        ref_media = self.project.media_by_id(ref_clip.media)
        if ref_media.kind == "audio":
            raise ValueError("reference clip must be video/image")
        ref_path = self.bundle.media_path(ref_media.path)
        mid = (ref_clip.src_in + ref_clip.src_out) // 2
        ref_t = self.project.timebase.frames_to_seconds(mid)
        ref_stats = _measure_frame_stats(ref_path, ref_t)

        if clip_ids is None:
            clip_ids = []
            for track in self.project.tracks:
                if track.kind != "video":
                    continue
                for c in track.clips:
                    if c.id != reference_clip_id:
                        clip_ids.append(c.id)

        matched: list[dict[str, Any]] = []
        for cid in clip_ids:
            track, clip = self._find_clip_and_track(cid)
            media = self.project.media_by_id(clip.media)
            if media.kind == "audio":
                continue
            path = self.bundle.media_path(media.path)
            t_mid = self.project.timebase.frames_to_seconds(
                (clip.src_in + clip.src_out) // 2
            )
            tgt_stats = _measure_frame_stats(path, t_mid)
            fx_list = _suggest_color_match_effects(
                ref_stats, tgt_stats, strength=strength,
            )
            for fx in fx_list:
                self.apply_effect(cid, fx)
            matched.append({
                "clip_id": cid,
                "effects": fx_list,
                "target_stats": {
                    "yavg": tgt_stats.get("yavg"),
                    "ravg": tgt_stats.get("ravg"),
                    "bavg": tgt_stats.get("bavg"),
                },
            })
        return {
            "reference_clip_id": reference_clip_id,
            "reference_stats": {
                "yavg": ref_stats.get("yavg"),
                "ravg": ref_stats.get("ravg"),
                "bavg": ref_stats.get("bavg"),
                "time_seconds": ref_t,
            },
            "strength": strength,
            "matched": matched,
            "matched_count": len(matched),
            "agent_note": (
                "Re-check with make_sequence_contact_sheet; strength>0.8 can look forced."
            ),
        }

    def analyze_asset(
        self,
        path: str | Path,
        *,
        do_scenes: bool = True,
        do_silence: bool = True,
        do_motion: bool = True,
        do_transcribe: bool = False,
        scene_backend: str = "auto",
        language: str | None = None,
        model_size: str = "base",
        cache: bool = True,
    ) -> dict[str, Any]:
        """Build an asset card (probe/scenes/silence/motion/optional ASR).

        When cache=True and a project is open, write JSON under bundle/analysis/.
        """
        card = _analyze_asset(
            Path(path),
            do_scenes=do_scenes,
            do_silence=do_silence,
            do_motion=do_motion,
            do_transcribe=do_transcribe,
            scene_backend=scene_backend,
            transcribe_language=language,
            model_size=model_size,
        )
        if cache:
            try:
                cache_path = _save_analysis_cache(self.bundle.root, card)
                card["cache_path"] = str(cache_path)
            except Exception:
                pass
        return card

    def load_asset_analysis(self, media_path: str | Path) -> dict[str, Any] | None:
        """Load a previously cached asset card from the open project."""
        return _load_analysis_cache(self.bundle.root, media_path)

    def separate_stems(
        self,
        path: str | Path,
        output_dir: str | Path,
        *,
        model: str = "htdemucs",
        two_stems: str | None = "vocals",
        device: str = "cpu",
    ) -> dict[str, Any]:
        """Separate vocals/accompaniment (Demucs). Returns stem file paths."""
        return _separate_stems(
            Path(path),
            Path(output_dir),
            model=model,
            two_stems=two_stems,
            device=device,
        )

    def caption_clip(
        self,
        clip_id: str,
        *,
        srt_path: str | Path | None = None,
        model_size: str = "base",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> dict[str, Any]:
        """Transcribe a clip's media, write SRT, apply subtitles effect.

        One undoable apply_effect for the subtitle burn-in; SRT is written
        next to the project bundle (or to srt_path). Returns
        {clip, srt_path, transcript}.
        """
        clip = self._find_clip(clip_id)
        media = self.project.media_by_id(clip.media)
        src = self.bundle.media_path(media.path)
        if not src.exists():
            raise FileNotFoundError(f"media file for clip {clip_id} not found: {src}")

        transcript = self.transcribe(
            src,
            model_size=model_size,
            language=language,
            device=device,
            compute_type=compute_type,
        )
        if srt_path is None:
            srt_path = self.bundle.root / f"captions_{clip_id}.srt"
        srt = self.write_srt(srt_path, transcript["segments"])
        updated = self.apply_effect(clip_id, {"type": "subtitles", "path": srt})
        return {
            "clip": updated.to_dict(),
            "srt_path": srt,
            "transcript": transcript,
        }

    # --- render -----------------------------------------------------------
    # Named delivery recipes for agents / UI (not encoder graphs).
    EXPORT_PRESETS: dict[str, dict[str, Any]] = {
        "draft": {
            "normalize_preset": None,
            "delivery_preset": "streaming",
            "run_delivery_check": False,
            "prepare": True,
            "description": "Fast iterate: export as-is, no loudnorm/check",
        },
        "streaming": {
            "normalize_preset": "streaming",
            "delivery_preset": "streaming",
            "run_delivery_check": True,
            "prepare": True,
            "description": "Web/social ~-14 LUFS + delivery_check",
        },
        "youtube": {
            "normalize_preset": "streaming",
            "delivery_preset": "streaming",
            "run_delivery_check": True,
            "prepare": True,
            "description": "Alias of streaming for YouTube-style loudness",
        },
        "broadcast": {
            "normalize_preset": "broadcast",
            "delivery_preset": "broadcast",
            "run_delivery_check": True,
            "prepare": True,
            "description": "Broadcast ~-23 LUFS + delivery_check",
        },
        "review": {
            "normalize_preset": None,
            "delivery_preset": "streaming",
            "run_delivery_check": False,
            "prepare": True,
            "run_review": True,
            "description": "Export + review_cut, no loudnorm",
        },
    }

    def list_export_presets(self) -> dict[str, Any]:
        """List named export recipes (normalize / delivery / prepare flags)."""
        items = [
            {"id": k, **dict(v)}
            for k, v in self.EXPORT_PRESETS.items()
        ]
        return {"count": len(items), "presets": items}

    def export_with_preset(
        self,
        output_path: str | Path,
        preset: str = "streaming",
        *,
        prepare: bool | None = None,
    ) -> dict[str, Any]:
        """Export using a named preset from list_export_presets.

        prepare=None uses preset default (usually fill/close gaps for base).
        """
        if preset not in self.EXPORT_PRESETS:
            raise ValueError(
                f"unknown export preset {preset!r}; "
                f"known: {sorted(self.EXPORT_PRESETS)}"
            )
        cfg = self.EXPORT_PRESETS[preset]
        do_prepare = cfg.get("prepare", True) if prepare is None else bool(prepare)
        prep = None
        if do_prepare:
            try:
                prep = self.prepare_export()
            except Exception as e:
                prep = {"error": str(e)[:500]}

        normalize = cfg.get("normalize_preset")
        written = self.export(Path(output_path), normalize_preset=normalize)
        result: dict[str, Any] = {
            "preset": preset,
            "path": str(written),
            "normalize_preset": normalize,
            "prepare": prep,
        }
        if cfg.get("run_review"):
            try:
                result["review"] = self.review_cut()
            except Exception as e:
                result["review_error"] = str(e)[:500]
        if cfg.get("run_delivery_check"):
            try:
                result["delivery_check"] = self.delivery_check(
                    written, preset=str(cfg.get("delivery_preset") or "streaming"),
                )
                result["delivery_ok"] = bool(
                    (result["delivery_check"] or {}).get("ok")
                )
            except Exception as e:
                result["delivery_check_error"] = str(e)[:500]
                result["delivery_ok"] = False
        result["agent_note"] = cfg.get("description", "")
        return result

    def export(
        self,
        output_path: Path,
        *,
        normalize_preset: str | None = None,
    ) -> Path:
        """Render timeline to ``output_path``.

        Optional ``normalize_preset`` (e.g. ``\"streaming\"``) writes a
        loudness-normalized sibling ``*_loud.ext`` and returns that path.
        Always run ``delivery_check`` on the result before calling it final.
        """
        written = self.render_backend.export(
            self.project, self.bundle, Path(output_path)
        )
        if normalize_preset:
            out = Path(written)
            loud_path = out.with_name(out.stem + "_loud" + out.suffix)
            self.normalize_loudness(out, loud_path, preset=normalize_preset)
            return Path(loud_path)
        return written

    def export_range(
        self,
        output_path: str | Path,
        start_seconds: float,
        end_seconds: float,
        *,
        normalize_preset: str | None = None,
        run_delivery_check: bool = False,
        delivery_preset: str = "streaming",
    ) -> dict[str, Any]:
        """Export the full timeline then cut [start, end) for a segment deliverable.

        Renders once (same cost as full export), then ffmpeg trims. Useful for
        cold-open / social cuts without a second graph. Not a dirty-region
        optimizer — still full encode first.
        """
        import subprocess
        import tempfile

        start = max(0.0, float(start_seconds))
        end = float(end_seconds)
        if end <= start:
            raise ValueError("end_seconds must be > start_seconds")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix="opmiere_full_", suffix=".mp4")
        import os
        os.close(fd)
        full = Path(raw)
        try:
            self.export(full, normalize_preset=None)
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner",
                    "-ss", f"{start:.3f}",
                    "-to", f"{end:.3f}",
                    "-i", str(full),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    str(output_path),
                ],
                capture_output=True, text=True,
            )
            if proc.returncode != 0 or not output_path.exists():
                raise RuntimeError(
                    f"export_range trim failed:\n{(proc.stderr or '')[-2000:]}"
                )
        finally:
            try:
                full.unlink(missing_ok=True)
            except OSError:
                pass
        written = output_path
        if normalize_preset:
            loud = output_path.with_name(output_path.stem + "_loud" + output_path.suffix)
            self.normalize_loudness(output_path, loud, preset=normalize_preset)
            written = loud
        result: dict[str, Any] = {
            "path": str(Path(written).resolve()),
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": round(end - start, 3),
            "normalize_preset": normalize_preset,
        }
        if run_delivery_check:
            result["delivery_check"] = self.delivery_check(
                written, preset=delivery_preset, match_project=True,
            )
        return result

    def export_preview(
        self,
        output_path: str | Path | None = None,
        *,
        height: int = 360,
        fps: float = 12.0,
        force: bool = False,
    ) -> dict[str, Any]:
        """Fast low-res timeline proxy for scrubbing (not delivery quality).

        If a fresh proxy already exists and force=False, returns it without
        re-encoding (cache hit). Otherwise lowers resolution, exports, restores.
        """
        import subprocess

        if height < 72 or height > 2160:
            raise ValueError("height must be in [72, 2160]")
        if fps <= 0 or fps > 60:
            raise ValueError("fps must be in (0, 60]")

        old_w, old_h = self.project.resolution.w, self.project.resolution.h
        default_proxy = self.bundle.root / "review" / "preview_proxy.mp4"
        if output_path is None:
            output_path = default_proxy
        output_path = Path(output_path)

        status = self.preview_proxy_status()
        if (
            not force
            and status.get("fresh")
            and status.get("path")
            and Path(status["path"]).exists()
        ):
            from .render.probe import probe as _probe
            info = _probe(Path(status["path"]))
            return {
                "path": status["path"],
                "width": info.width,
                "height": info.height,
                "fps": info.fps,
                "duration_seconds": info.duration_seconds,
                "project_resolution": {"w": old_w, "h": old_h},
                "proxy_height": info.height,
                "proxy_fps_request": fps,
                "fingerprint": self._preview_proxy_fingerprint,
                "fresh": True,
                "cache_hit": True,
                "quick": False,
                "agent_note": "Reused fresh proxy (no re-encode).",
            }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        aspect = old_w / max(old_h, 1)
        new_h = int(height) // 2 * 2
        new_w = max(2, int(round(new_h * aspect)) // 2 * 2)
        # Interactive edits: low res → ultrafast; normal scrub → veryfast
        enc_preset = "ultrafast" if new_h <= 240 else "veryfast"
        enc_crf = "30" if new_h <= 240 else "28"
        try:
            self.project.resolution.w = new_w
            self.project.resolution.h = new_h
            written = self.render_backend.export(
                self.project, self.bundle, output_path.with_suffix(".full.mp4")
            )
        finally:
            self.project.resolution.w = old_w
            self.project.resolution.h = old_h

        proxy = Path(output_path)
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner",
                "-i", str(written),
                "-vf", f"fps={fps}",
                "-an",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", enc_preset, "-crf", enc_crf,
                str(proxy),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not proxy.exists():
            if written.exists() and written != proxy:
                try:
                    written.replace(proxy)
                except OSError:
                    pass
            if not proxy.exists():
                raise RuntimeError(
                    f"export_preview failed:\n{(proc.stderr or '')[-2000:]}"
                )
        else:
            try:
                written.unlink(missing_ok=True)
            except OSError:
                pass

        self._preview_proxy_path = str(proxy.resolve())
        self._preview_proxy_fingerprint = self._timeline_fingerprint()
        self._preview_proxy_height = new_h
        self._preview_proxy_fps = float(fps)
        from .render.probe import probe as _probe
        info = _probe(proxy)
        return {
            "path": self._preview_proxy_path,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "duration_seconds": info.duration_seconds,
            "project_resolution": {"w": old_w, "h": old_h},
            "proxy_height": new_h,
            "proxy_fps_request": fps,
            "encode_preset": enc_preset,
            "fingerprint": self._preview_proxy_fingerprint,
            "fresh": True,
            "cache_hit": False,
            "quick": new_h <= 240,
            "agent_note": (
                "Scrub proxy only — not for delivery. Auto-invalidated on "
                "timeline mutate/undo/redo; re-run export_preview after edits."
            ),
        }

    def ensure_preview_proxy(
        self,
        output_path: str | Path | None = None,
        *,
        height: int = 360,
        fps: float = 12.0,
    ) -> dict[str, Any]:
        """Build proxy only if missing or stale; else return cache hit."""
        return self.export_preview(
            output_path, height=height, fps=fps, force=False,
        )

    def refresh_preview_proxy(
        self,
        *,
        quick: bool = False,
        force: bool | None = None,
        height: int | None = None,
        fps: float | None = None,
    ) -> dict[str, Any]:
        """Rebuild scrub proxy when stale (or force). Used after timeline drags.

        quick=True → ~180p / 8fps / ultrafast for snappy UI feedback.
        force=None → rebuild only if not fresh; force=True always; False never.
        """
        status = self.preview_proxy_status()
        if force is False:
            return {
                **status,
                "cache_hit": True,
                "skipped": True,
                "agent_note": "force=false — no rebuild",
            }
        need = True if force is True else (not status.get("fresh"))
        if not need:
            return self.export_preview(
                height=height or self._preview_proxy_height,
                fps=fps or self._preview_proxy_fps,
                force=False,
            )
        if quick:
            h = height if height is not None else 180
            f = fps if fps is not None else 8.0
        else:
            h = height if height is not None else int(self._preview_proxy_height or 360)
            f = fps if fps is not None else float(self._preview_proxy_fps or 12.0)
        result = self.export_preview(height=h, fps=f, force=True)
        result["refreshed"] = True
        result["quick"] = bool(quick)
        return result

    def review_keyframes(
        self,
        output_dir: str | Path,
        *,
        count: int = 5,
        width: int = 640,
        ensure_proxy: bool = True,
    ) -> dict[str, Any]:
        """Extract evenly spaced frames across the cut for agent eyes.

        Times at 0%, …, 100% of duration. Uses fresh proxy when possible.
        """
        if count < 2 or count > 24:
            raise ValueError("count must be in [2, 24]")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if ensure_proxy:
            self.ensure_preview_proxy()
        dur_f = self.duration_frames()
        fps = float(self.project.timebase.fps or 30.0)
        dur_s = dur_f / fps if fps else 0.0
        if dur_s <= 0:
            raise ValueError("empty timeline — nothing to review")
        frames: list[dict[str, Any]] = []
        for i in range(count):
            if count == 1:
                t = 0.0
            else:
                t = dur_s * i / (count - 1)
            # avoid exact end EOF on some demuxers
            t = min(t, max(0.0, dur_s - 0.05))
            out = output_dir / f"keyframe_{i:02d}_{t:.2f}s.jpg"
            r = self.frame_at(t, out, width=width, prefer_proxy=True)
            frames.append({
                "index": i,
                "time_seconds": round(t, 3),
                "path": r["path"],
                "mode": r.get("mode"),
            })
        return {
            "duration_seconds": round(dur_s, 3),
            "count": len(frames),
            "frames": frames,
            "proxy": self.preview_proxy_status(),
            "agent_note": (
                "Read these images in order for pacing/continuity. "
                "Not a substitute for delivery_check on the final export."
            ),
        }

    def preview_range(
        self,
        output_path: str | Path,
        start_seconds: float,
        end_seconds: float,
        *,
        ensure_proxy: bool = True,
        height: int = 360,
        fps: float = 12.0,
    ) -> dict[str, Any]:
        """Cheap segment proxy: cut a time range from a *fresh* full proxy.

        Does not re-render the timeline graph — only ffmpeg -ss/-to on the
        scrub proxy. Use after ensure_preview_proxy for focused review.
        """
        import subprocess

        start = max(0.0, float(start_seconds))
        end = float(end_seconds)
        if end <= start:
            raise ValueError(f"end_seconds ({end}) must be > start_seconds ({start})")
        if ensure_proxy:
            self.ensure_preview_proxy(height=height, fps=fps)
        status = self.preview_proxy_status()
        if not status.get("fresh") or not status.get("path"):
            raise ValueError(
                "no fresh preview proxy — call ensure_preview_proxy first "
                f"(status={status})"
            )
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner",
                "-ss", f"{start:.3f}",
                "-to", f"{end:.3f}",
                "-i", str(status["path"]),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-an",
                str(output_path),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                f"preview_range failed:\n{(proc.stderr or '')[-1500:]}"
            )
        return {
            "path": str(output_path.resolve()),
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": round(end - start, 3),
            "source_proxy": status["path"],
            "agent_note": (
                "Segment from full scrub proxy only — not delivery quality."
            ),
        }

    def suggest_room_tone(
        self,
        path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Find a quiet donor segment in a take for ambience fill."""
        return _suggest_room_tone(path, **kwargs)

    def extract_room_tone(
        self,
        path: str | Path,
        output_path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Extract (and optional loop) room tone WAV from a donor range."""
        return _extract_room_tone(path, output_path, **kwargs)

    def place_room_tone(
        self,
        source_path: str | Path,
        track_id: str | None = None,
        *,
        start_frame: int = 0,
        loop_to_seconds: float | None = None,
        gain_db: float = -8.0,
        output_wav: str | Path | None = None,
    ) -> dict[str, Any]:
        """Suggest + extract room tone and place on an audio track under the cut.

        Creates an audio track if track_id is None. Applies gain_db on the clip.
        """
        import tempfile

        src = Path(source_path)
        if output_wav is None:
            # Outside media/ so place_from_file can import without collision
            td = Path(tempfile.mkdtemp(prefix="opmiere_rt_"))
            output_wav = td / f"room_tone_{new_id('rt')}.wav"
        # duration of bed: timeline length or explicit loop
        fps = float(self.project.timebase.fps or 30.0)
        if loop_to_seconds is None:
            loop_to_seconds = max(0.5, self.duration_frames() / fps)
        extracted = self.extract_room_tone(
            src, output_wav, loop_to_seconds=loop_to_seconds,
        )
        if track_id is None:
            track_id = self.add_track("audio").id
        clip = self.place_from_file(
            Path(extracted["path"]), "audio", track_id, start=start_frame,
        )
        if abs(float(gain_db)) >= 0.1:
            clip = self.apply_effect(clip.id, {"type": "gain", "db": float(gain_db)})
        return {
            "clip": clip.to_dict(),
            "track_id": track_id,
            "extracted": extracted,
            "gain_db": gain_db,
            "agent_note": (
                "Room tone under dialogue; duck or lower further if it muddies VO."
            ),
        }

    def extract_frame(
        self,
        path: str | Path,
        time_seconds: float,
        output_path: str | Path,
        *,
        width: int = 640,
    ) -> dict[str, Any]:
        """Extract one JPEG/PNG frame from a media file at time_seconds."""
        import subprocess

        path = Path(path)
        output_path = Path(output_path)
        if not path.exists():
            raise FileNotFoundError(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        t = max(0.0, float(time_seconds))
        w = max(16, int(width))
        # -ss before -i for fast seek; fine for proxy scrub
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner",
                "-ss", f"{t:.3f}",
                "-i", str(path),
                "-frames:v", "1",
                "-vf", f"scale={w}:-1",
                str(output_path),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                f"extract_frame failed @ {t:.3f}s:\n{(proc.stderr or '')[-1500:]}"
            )
        return {
            "path": str(output_path.resolve()),
            "time_seconds": t,
            "source": str(path),
            "width": w,
        }

    def frame_at(
        self,
        time_seconds: float,
        output_path: str | Path,
        *,
        width: int = 640,
        prefer_proxy: bool = True,
    ) -> dict[str, Any]:
        """Frame at timeline time for cheap scrub eyes.

        Prefer last export_preview proxy when available (includes overlays).
        Else approximate from base video track source media (overlays ignored).
        """
        t = max(0.0, float(time_seconds))
        output_path = Path(output_path)
        status = self.preview_proxy_status()
        if prefer_proxy and status.get("fresh"):
            result = self.extract_frame(
                status["path"], t, output_path, width=width,
            )
            result["mode"] = "proxy"
            result["proxy_fresh"] = True
            return result
        stale_note = None
        if prefer_proxy and status.get("exists") and not status.get("fresh"):
            stale_note = "proxy stale after timeline edit — used base_track"

        # Base-track source seek
        video_tracks = [tr for tr in self.project.tracks if tr.kind == "video"]
        if not video_tracks or not video_tracks[0].clips:
            raise ValueError("no base video clips — build a timeline or export_preview first")
        base = video_tracks[0]
        fps = float(self.project.timebase.fps or 30.0)
        t_frame = int(round(t * fps))
        clip = None
        for c in base.clips_in_order():
            if c.start <= t_frame < c.end:
                clip = c
                break
        if clip is None:
            # clamp to last frame of last clip
            ordered = base.clips_in_order()
            clip = ordered[-1]
            t_frame = max(clip.start, min(t_frame, clip.end - 1))

        media = self.project.media_by_id(clip.media)
        media_path = self.bundle.media_path(media.path)
        mode = "base_track"
        if media.proxy_path:
            proxy_abs = self.bundle.resolve_bundle_path(media.proxy_path)
            if proxy_abs.exists():
                media_path = proxy_abs
                mode = "media_proxy"
        # map timeline → source seconds
        local = t_frame - clip.start
        if clip.transition_in:
            # still inside clip's timeline footprint
            pass
        src_frame = clip.src_in + int(round(local * clip.speed))
        src_frame = min(max(src_frame, clip.src_in), max(clip.src_in, clip.src_out - 1))
        src_t = self.project.timebase.frames_to_seconds(src_frame)
        result = self.extract_frame(media_path, src_t, output_path, width=width)
        result["mode"] = mode
        result["clip_id"] = clip.id
        result["proxy_fresh"] = False
        note = (
            "Base-track approximation (overlays/effects may differ). "
            "Call export_preview for fuller picture."
            if mode == "base_track"
            else "Seek via per-asset media proxy (effects/overlays not applied)."
        )
        if stale_note:
            note = stale_note + ". " + note
        result["agent_note"] = note
        return result
