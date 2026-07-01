"""Opmiere project model — the engine-independent source of truth.

Design rules (see ARCHITECTURE.md sections 3 and 6):
- Agent-legible: stable prefixed ids, explicit units. Time is in **frames** over an
  explicit timebase, never bare seconds.
- Engine-independent: this model knows nothing about ffmpeg or any renderer. A
  RenderBackend compiles it down; swapping engines never touches this file.

JSON field names follow the ARCHITECTURE.md section 6 sketch: a clip serialises its
source trim as ``in`` / ``out`` (Python keywords, so stored as ``src_in`` / ``src_out``
on the dataclass and mapped during (de)serialisation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
import uuid

__all__ = [
    "Timebase",
    "Resolution",
    "Media",
    "Clip",
    "Track",
    "Project",
    "MediaKind",
    "TrackKind",
    "new_id",
    "KNOWN_EFFECT_TYPES",
]

SCHEMA_VERSION = 1

MediaKind = Literal["video", "image", "audio"]
TrackKind = Literal["video", "audio"]

# The deterministic-effect vocabulary (ARCHITECTURE.md section 5.8). Single
# source of truth: ops.py validates against this set, render/ffmpeg.py
# interprets it. Effects that would change a clip's timeline duration (e.g.
# speed/time-remap) are deliberately excluded until Clip's duration accounting
# supports them — adding them here without that would silently desync the
# timeline math the P0 render backend relies on.
KNOWN_EFFECT_TYPES = {"color", "fade"}


def new_id(prefix: str) -> str:
    """A short, stable, human-readable id, e.g. ``clp_9f3a1c``.

    Public: the Operation API (ops.py) needs to mint new clip ids too (e.g.
    ``split_clip`` creating a second clip), not just this module.
    """
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


@dataclass
class Timebase:
    """The project clock. Frames are the unit of time everywhere else."""

    fps: float = 30.0
    sample_rate: int = 48000

    def frames_to_seconds(self, frames: int) -> float:
        return frames / self.fps

    def seconds_to_frames(self, seconds: float) -> int:
        return round(seconds * self.fps)

    def to_dict(self) -> dict[str, Any]:
        return {"fps": self.fps, "sample_rate": self.sample_rate}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Timebase":
        return cls(fps=d.get("fps", 30.0), sample_rate=d.get("sample_rate", 48000))


@dataclass
class Resolution:
    w: int = 1920
    h: int = 1080

    def to_dict(self) -> dict[str, Any]:
        return {"w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Resolution":
        return cls(w=d.get("w", 1920), h=d.get("h", 1080))


@dataclass
class Media:
    """A source asset. ``path`` is relative to the bundle's ``media/`` folder."""

    id: str
    kind: MediaKind
    path: str
    duration_frames: int = 0
    has_audio: bool = False
    # For generated assets: {"provider","job","prompt",...} — lets an agent reason
    # about how a clip came to exist and regenerate it. None for imported media.
    origin: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "duration_frames": self.duration_frames,
            "has_audio": self.has_audio,
        }
        if self.origin is not None:
            d["origin"] = self.origin
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Media":
        return cls(
            id=d["id"],
            kind=d["kind"],
            path=d["path"],
            duration_frames=d.get("duration_frames", 0),
            has_audio=d.get("has_audio", False),
            origin=d.get("origin"),
        )


@dataclass
class Clip:
    """A source range placed on a track.

    - ``start``   : timeline position, in frames.
    - ``src_in``  : first source frame used (JSON: ``in``).
    - ``src_out`` : end source frame, exclusive (JSON: ``out``).

    Timeline duration is ``src_out - src_in``.
    """

    id: str
    media: str  # Media.id
    start: int
    src_in: int
    src_out: int
    effects: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_frames(self) -> int:
        return self.src_out - self.src_in

    @property
    def end(self) -> int:
        """Timeline frame where this clip ends (exclusive)."""
        return self.start + self.duration_frames

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "media": self.media,
            "start": self.start,
            "in": self.src_in,
            "out": self.src_out,
            "effects": self.effects,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Clip":
        return cls(
            id=d["id"],
            media=d["media"],
            start=d["start"],
            src_in=d["in"],
            src_out=d["out"],
            effects=d.get("effects", []),
        )


@dataclass
class Track:
    id: str
    kind: TrackKind
    clips: list[Clip] = field(default_factory=list)

    def clips_in_order(self) -> list[Clip]:
        return sorted(self.clips, key=lambda c: c.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "clips": [c.to_dict() for c in self.clips],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Track":
        return cls(
            id=d["id"],
            kind=d["kind"],
            clips=[Clip.from_dict(c) for c in d.get("clips", [])],
        )


@dataclass
class Project:
    """Root document. Serialised as ``project.json`` inside a ``.opm`` bundle."""

    id: str = field(default_factory=lambda: new_id("prj"))
    timebase: Timebase = field(default_factory=Timebase)
    resolution: Resolution = field(default_factory=Resolution)
    media: list[Media] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    schema: int = SCHEMA_VERSION

    # --- lookup -----------------------------------------------------------
    def media_by_id(self, media_id: str) -> Media:
        for m in self.media:
            if m.id == media_id:
                return m
        raise KeyError(f"no media with id {media_id!r}")

    def track_by_id(self, track_id: str) -> Track:
        for t in self.tracks:
            if t.id == track_id:
                return t
        raise KeyError(f"no track with id {track_id!r}")

    # --- mutation (seed of the P1 Operation API) --------------------------
    def add_media(
        self,
        kind: MediaKind,
        path: str,
        duration_frames: int = 0,
        has_audio: bool = False,
        origin: dict[str, Any] | None = None,
    ) -> Media:
        m = Media(new_id("med"), kind, path, duration_frames, has_audio, origin)
        self.media.append(m)
        return m

    def add_track(self, kind: TrackKind) -> Track:
        t = Track(new_id("trk"), kind)
        self.tracks.append(t)
        return t

    def add_clip(
        self,
        track: Track,
        media: Media,
        start: int,
        src_in: int,
        src_out: int,
    ) -> Clip:
        if src_out <= src_in:
            raise ValueError(f"clip out ({src_out}) must be > in ({src_in})")
        if media.duration_frames and src_out > media.duration_frames:
            raise ValueError(
                f"clip out ({src_out}) exceeds media duration "
                f"({media.duration_frames}) of {media.id}"
            )
        c = Clip(new_id("clp"), media.id, start, src_in, src_out)
        track.clips.append(c)
        return c

    def duration_frames(self) -> int:
        """Timeline length: the furthest clip end across all tracks."""
        return max((c.end for t in self.tracks for c in t.clips), default=0)

    # --- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "timebase": self.timebase.to_dict(),
            "resolution": self.resolution.to_dict(),
            "media": [m.to_dict() for m in self.media],
            "tracks": [t.to_dict() for t in self.tracks],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        return cls(
            id=d["id"],
            timebase=Timebase.from_dict(d.get("timebase", {})),
            resolution=Resolution.from_dict(d.get("resolution", {})),
            media=[Media.from_dict(m) for m in d.get("media", [])],
            tracks=[Track.from_dict(t) for t in d.get("tracks", [])],
            schema=d.get("schema", SCHEMA_VERSION),
        )
