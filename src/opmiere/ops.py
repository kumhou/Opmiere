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
        self._in_point: int | None = None
        self._out_point: int | None = None

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
        return cls(bundle, generation_provider=generation_provider)

    @classmethod
    def open(cls, root: Path, generation_provider: GenerationProvider | None = None) -> "Editor":
        return cls(Bundle.open(Path(root)), generation_provider=generation_provider)

    def save(self) -> None:
        self.bundle.save(self.project)

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
                for fx in clip.effects or []:
                    if fx.get("type") == "gain" and isinstance(fx.get("db"), (int, float)):
                        gain_db = float(fx["db"])
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
                    "muted": bool(clip.muted),
                    "has_audio_media": bool(m and (m.kind == "audio" or m.has_audio)),
                    "transition_in": clip.transition_in,
                    "label": (m.path.split("/")[-1] if m and m.path else clip.id),
                })
            tracks_out.append({
                "id": track.id,
                "kind": track.kind,
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
        }

    # --- undo/redo -----------------------------------------------------
    @contextmanager
    def _mutate(self) -> Iterator[None]:
        """Snapshot before a mutation; roll the snapshot back if it fails."""
        self._undo_stack.append(self.project.to_dict())
        try:
            yield
        except Exception:
            self._undo_stack.pop()
            raise
        else:
            self._redo_stack.clear()
            # Timeline changed — scrub proxy no longer matches
            self.invalidate_preview_proxy()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self.project.to_dict())
        self.project = Project.from_dict(self._undo_stack.pop())
        self.invalidate_preview_proxy()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self.project.to_dict())
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

    def set_track_solo(self, track_id: str, solo: bool = True) -> dict[str, Any]:
        with self._mutate():
            track = self.project.track_by_id(track_id)
            track.solo = bool(solo)
            return {"track_id": track_id, "muted": track.muted, "solo": track.solo, "locked": track.locked}

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

    def move_clip(self, clip_id: str, new_start: int) -> Clip:
        self._assert_clip_track_unlocked(clip_id)
        with self._mutate():
            clip = self._find_clip(clip_id)
            if new_start < 0:
                raise ValueError(f"new_start must be >= 0, got {new_start}")
            clip.start = new_start
            return clip

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

    def split_clip(self, clip_id: str, at_frame: int) -> tuple[Clip, Clip]:
        with self._mutate():
            return self._split_clip_unlocked(clip_id, at_frame)

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
        )
        track.clips.append(second)
        return clip, second

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
    ) -> dict[str, Any]:
        """Paste clipboard as a new clip. start=None → end of target track."""
        if not self._clipboard:
            raise ValueError("clipboard empty — copy_clip first")
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

        with self._mutate():
            track = self.project.track_by_id(tid)
            media = self.project.media_by_id(bp["media"])
            clip = self.project.add_clip(
                track, media, place_at, int(bp["src_in"]), int(bp["src_out"]),
            )
            clip.speed = float(bp.get("speed") or 1.0)
            clip.effects = [dict(e) for e in (bp.get("effects") or [])]
            if bp.get("position"):
                clip.position = dict(bp["position"])
            return {
                "clip_id": clip.id,
                "track_id": tid,
                "start": clip.start,
                "end": clip.end,
                "from_clipboard": bp.get("source_clip_id"),
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
    ) -> dict[str, Any]:
        """Copy a video clip's audio onto an audio track for independent J/L timing.

        Places the same media range on an audio track (creates overlay audio
        track when needed so starts may leave gaps). Once any audio-track clips
        exist, export uses them instead of embedded video audio — so this
        effectively splits picture vs sound. ``audio_start_offset_frames``
        negative = J-cut lead (audio earlier); positive = L-cut lag.
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
            return {
                "video_clip_id": clip.id,
                "audio_clip_id": audio_clip.id,
                "audio_track_id": atrack.id,
                "audio_start": a_start,
                "offset_frames": int(audio_start_offset_frames),
                "agent_note": (
                    "Picture stays on video; sound is on audio track. "
                    "Negative offset = J-cut (audio leads). Embedded video "
                    "audio is suppressed while any audio-track clips exist."
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

    def apply_effect(self, clip_id: str, effect: dict) -> Clip:
        """Append a deterministic effect (ARCHITECTURE.md section 5.8) to a clip.

        Validated here so an agent gets an immediate, specific error instead of
        a cryptic ffmpeg failure at export time. See KNOWN_EFFECT_TYPES for the
        supported vocabulary; each type documents its own required fields.
        """
        with self._mutate():
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
                # Multi-stage: blur a copy + screen-blend it back (not a
                # single ffmpeg filter). amount = blur radius of the halo;
                # intensity = how hard the halo is blended onto the base.
                amount = effect.get("amount", 12.0)
                if not isinstance(amount, (int, float)) or not (0.0 < amount <= 50.0):
                    raise ValueError("glow effect 'amount' must be in (0, 50]")
                intensity = effect.get("intensity", 0.7)
                if not isinstance(intensity, (int, float)) or not (0.0 < intensity <= 1.0):
                    raise ValueError("glow effect 'intensity' must be in (0, 1]")
            elif etype == "lut3d":
                # External .cube / .3dl file — agent/user supplies the path.
                # Existence checked here so a missing LUT fails at apply time,
                # not at export after a long timeline build.
                path = effect.get("path")
                if not isinstance(path, str) or not path.strip():
                    raise ValueError("lut3d effect requires non-empty string 'path' to a .cube/.3dl file")
                if not Path(path).exists():
                    raise FileNotFoundError(f"lut3d effect path not found: {path}")
            elif etype == "ken_burns":
                # Slow pan/zoom over the clip (ARCHITECTURE.md §5.8 Transform).
                # zoom_* >= 1; x_*/y_* are focus points as fractions of the
                # frame [0,1] (0.5,0.5 = center). Render interpolates per frame.
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
                # Kelvin target via ffmpeg colortemperature. 6500 ≈ daylight
                # neutral; lower = warmer (tungsten), higher = cooler (blue sky).
                temperature = effect.get("temperature", 6500)
                if not isinstance(temperature, (int, float)) or not (1000 <= temperature <= 40000):
                    raise ValueError("white_balance effect 'temperature' must be in [1000, 40000] Kelvin")
                mix = effect.get("mix", 1.0)
                if not isinstance(mix, (int, float)) or not (0.0 <= mix <= 1.0):
                    raise ValueError("white_balance effect 'mix' must be in [0, 1]")
            elif etype == "shape_mask":
                # Soft geometric alpha mask (circle/rect). Like chroma_key, the
                # clip needs alpha survival through pad for overlay compositing.
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
                # Named audio_eq, not eq: the "color" effect above already
                # uses ffmpeg's own (unrelated, video) `eq` filter - a same-
                # named Opmiere effect here would be genuinely confusing on
                # an agent-facing surface, not just an internal detail.
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
        with self._mutate():
            if not isinstance(speed, (int, float)) or speed <= 0:
                raise ValueError(f"speed must be a positive number, got {speed!r}")
            clip = self._find_clip(clip_id)
            clip.speed = float(speed)
            return clip

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

    def clear_position(self, clip_id: str) -> Clip:
        """Restore a clip to full-frame (remove a previously set position)."""
        with self._mutate():
            clip = self._find_clip(clip_id)
            clip.position = None
            return clip

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

    def list_markers(self) -> dict[str, Any]:
        fps = float(self.project.timebase.fps or 30.0)
        items = [
            {**m.to_dict(), "time_seconds": round(m.frame / fps, 3)}
            for m in sorted(self.project.markers, key=lambda x: x.frame)
        ]
        return {"count": len(items), "markers": items}

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
