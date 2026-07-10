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
from .render.look import LOOK_PRESETS as _LOOK_PRESETS
from .render.look import measure_frame_stats as _measure_frame_stats
from .render.look import resolve_look as _resolve_look
from .render.look import suggest_color_match_effects as _suggest_color_match_effects
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
        # No default provider: generation is optional and pluggable (section
        # 4 principle 3) - unlike rendering, there's no single obvious
        # default (local vs cloud, which model), so the caller must choose.
        self.generation_provider = generation_provider
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

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
    ) -> Media:
        """Import media.

        conform=True: re-encode when source fps ≠ project.
        fit: none | contain (letterbox) | cover (crop-fill) to project resolution.
        """
        with self._mutate():
            return _ffmpeg_import_media(
                self.bundle,
                self.project,
                Path(src_path),
                kind,
                origin=origin,
                conform=conform,
                fit=fit,
            )

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

    def move_clip(self, clip_id: str, new_start: int) -> Clip:
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

    def split_clip(self, clip_id: str, at_frame: int) -> tuple[Clip, Clip]:
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            if not (clip.start < at_frame < clip.end):
                raise ValueError(
                    f"split point {at_frame} must be strictly inside clip "
                    f"{clip_id} ({clip.start}..{clip.end})"
                )
            split_src = clip.src_in + (at_frame - clip.start)
            original_out = clip.src_out
            clip.src_out = split_src
            second = Clip(
                id=new_id("clp"),
                media=clip.media,
                start=at_frame,
                src_in=split_src,
                src_out=original_out,
            )
            track.clips.append(second)
            return clip, second

    def delete_clip(self, clip_id: str) -> Clip:
        with self._mutate():
            track, clip = self._find_clip_and_track(clip_id)
            track.clips.remove(clip)
            return clip

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
                "agent_note": "Reused fresh proxy (no re-encode).",
            }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        aspect = old_w / max(old_h, 1)
        new_h = int(height) // 2 * 2
        new_w = max(2, int(round(new_h * aspect)) // 2 * 2)
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
                "-preset", "veryfast", "-crf", "28",
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
            "fingerprint": self._preview_proxy_fingerprint,
            "fresh": True,
            "cache_hit": False,
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
        # map timeline → source seconds
        local = t_frame - clip.start
        if clip.transition_in:
            # still inside clip's timeline footprint
            pass
        src_frame = clip.src_in + int(round(local * clip.speed))
        src_frame = min(max(src_frame, clip.src_in), max(clip.src_in, clip.src_out - 1))
        src_t = self.project.timebase.frames_to_seconds(src_frame)
        result = self.extract_frame(media_path, src_t, output_path, width=width)
        result["mode"] = "base_track"
        result["clip_id"] = clip.id
        result["proxy_fresh"] = False
        note = (
            "Base-track approximation (overlays/effects may differ). "
            "Call export_preview for fuller picture."
        )
        if stale_note:
            note = stale_note + ". " + note
        result["agent_note"] = note
        return result
