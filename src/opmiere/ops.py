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
from typing import Iterator

from .bundle import Bundle
from .model import (
    KNOWN_EFFECT_TYPES,
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
from .render.ffmpeg import FFmpegBackend
from .render.ffmpeg import import_media as _ffmpeg_import_media


class Editor:
    """Wraps a Project + Bundle. The only supported way to mutate either."""

    def __init__(self, bundle: Bundle, render_backend: RenderBackend | None = None):
        self.bundle = bundle
        self.project: Project = bundle.load()
        self.render_backend = render_backend or FFmpegBackend()
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

    @classmethod
    def create(
        cls,
        root: Path,
        fps: float = 30.0,
        width: int = 1920,
        height: int = 1080,
    ) -> "Editor":
        project = Project()
        project.timebase.fps = fps
        project.resolution.w, project.resolution.h = width, height
        bundle = Bundle.create(Path(root), project=project)
        return cls(bundle)

    @classmethod
    def open(cls, root: Path) -> "Editor":
        return cls(Bundle.open(Path(root)))

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
            clip.effects.append(dict(effect))
            return clip

    # --- render -----------------------------------------------------------
    def export(self, output_path: Path) -> Path:
        return self.render_backend.export(self.project, self.bundle, Path(output_path))
