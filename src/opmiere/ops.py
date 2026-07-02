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

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .bundle import Bundle
from .generation.provider import GenerationJob, GenerationProvider, JobStatus
from .model import (
    CURVES_PRESETS,
    KNOWN_EFFECT_TYPES,
    KNOWN_TRANSITION_TYPES,
    TEXT_POSITIONS,
    Clip,
    Media,
    MediaKind,
    Project,
    Track,
    TrackKind,
    new_id,
)
from .render.backend import RenderBackend
from .render.contact_sheet import make_contact_sheet as _make_contact_sheet
from .render.ffmpeg import FFmpegBackend
from .render.ffmpeg import import_media as _ffmpeg_import_media
from .render.quality_check import quality_check as _quality_check

# Maps a GenerationJob.kind (what an agent asked to generate) to the
# Media.kind it becomes once it's a file on disk. image/video are their own
# media kind; speech/sfx/music are all just "audio" once generated; upscale
# always produces an "image" (video upscale is not implemented - see
# _build_upscale_workflow).
_GENERATION_KIND_TO_MEDIA_KIND = {"speech": "audio", "sfx": "audio", "music": "audio", "upscale": "image"}


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
        # No default provider: generation is optional and pluggable (section
        # 4 principle 3) - unlike rendering, there's no single obvious
        # default (local vs cloud, which model), so the caller must choose.
        self.generation_provider = generation_provider
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

    @classmethod
    def create(
        cls,
        root: Path,
        fps: float = 30.0,
        width: int = 1920,
        height: int = 1080,
        generation_provider: GenerationProvider | None = None,
    ) -> "Editor":
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

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self.project.to_dict())
        self.project = Project.from_dict(self._undo_stack.pop())
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self.project.to_dict())
        self.project = Project.from_dict(self._redo_stack.pop())
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
    def import_media(self, src_path: Path, kind: MediaKind) -> Media:
        with self._mutate():
            return _ffmpeg_import_media(self.bundle, self.project, Path(src_path), kind)

    def add_track(self, kind: TrackKind) -> Track:
        with self._mutate():
            return self.project.add_track(kind)

    def add_clip(
        self, track_id: str, media_id: str, start: int, src_in: int, src_out: int
    ) -> Clip:
        with self._mutate():
            track = self.project.track_by_id(track_id)
            media = self.project.media_by_id(media_id)
            return self.project.add_clip(track, media, start, src_in, src_out)

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
        media_kind = _GENERATION_KIND_TO_MEDIA_KIND.get(job.kind, job.kind)
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

    # --- render -----------------------------------------------------------
    def export(self, output_path: Path) -> Path:
        return self.render_backend.export(self.project, self.bundle, Path(output_path))
