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
    "Marker",
    "Project",
    "MediaKind",
    "TrackKind",
    "new_id",
    "KNOWN_EFFECT_TYPES",
    "DEFAULT_TEXT_FONT",
    "TEXT_POSITIONS",
    "CURVES_PRESETS",
    "KNOWN_TRANSITION_TYPES",
    "IMAGE_VIRTUAL_DURATION_FRAMES",
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
KNOWN_EFFECT_TYPES = {
    "color", "fade", "gain", "text", "blur", "vignette", "chroma_key", "luma_key", "curves",
    "crop", "rotate", "sharpen", "film_grain", "glow", "lut3d", "ken_burns", "white_balance",
    "shape_mask", "subtitles", "compression", "noise_reduction", "audio_eq", "opacity",
}

SHAPE_MASK_SHAPES = {"circle", "rect"}

# "text" effect defaults. A CJK-capable font is the right default for this
# product (JH's primary language is Chinese) — Arial-style defaults would
# silently render CJK captions as tofu boxes. Verified present on Windows
# 10/11 by default. Render-time raises a clear error if it's ever missing
# rather than letting ffmpeg fail with an opaque filter-parse error.
DEFAULT_TEXT_FONT = r"C:\Windows\Fonts\msyh.ttc"
TEXT_POSITIONS = {"top", "center", "bottom"}

# "curves" effect presets — ffmpeg's own curves filter vocabulary (its own
# `preset` enum names, verified via `ffmpeg -h filter=curves`), not invented.
CURVES_PRESETS = {
    "color_negative", "cross_process", "darker", "increase_contrast", "lighter",
    "linear_contrast", "medium_contrast", "negative", "strong_contrast", "vintage",
}

# Transitions between adjacent clips on a track (ARCHITECTURE.md section 5.8).
# Kept separate from KNOWN_EFFECT_TYPES: an effect is about one clip's own
# pixels, a transition is about the *relationship* between two clips. Each
# maps to one of ffmpeg xfade's own transition names (see render/ffmpeg.py's
# _XFADE_TRANSITION_BY_TYPE) - this is a curated subset of xfade's real 57,
# picked to match §5.8's own wishlist ("dip-to-black/white, wipes"), not
# exhaustive.
KNOWN_TRANSITION_TYPES = {
    "cross_dissolve", "dip_to_black", "dip_to_white",
    "wipe_left", "wipe_right", "wipe_up", "wipe_down",
}

# A still image has no intrinsic duration the way video/audio do (there's
# nothing to probe). This is a deliberate virtual/sentinel value — not a
# guessed fact — generous enough that any reasonable on-screen duration an
# agent picks fits within add_clip's src_out <= media.duration_frames check.
# ~1 hour at 30fps.
IMAGE_VIRTUAL_DURATION_FRAMES = 108_000


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
    # Optional low-res scrub proxy, path relative to bundle root (e.g. proxies/med_x.mp4).
    proxy_path: str | None = None

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
        if self.proxy_path is not None:
            d["proxy_path"] = self.proxy_path
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
            proxy_path=d.get("proxy_path"),
        )


@dataclass
class Clip:
    """A source range placed on a track.

    - ``start``   : timeline position, in frames.
    - ``src_in``  : first source frame used (JSON: ``in``).
    - ``src_out`` : end source frame, exclusive (JSON: ``out``).
    - ``speed``   : playback rate multiplier (1.0 = normal). Does not change
      src_in/src_out (still "how much source material"); it changes how many
      timeline frames that material occupies — see timeline_duration_frames.
      Kept as its own field rather than an entry in ``effects``, like
      transition_in: it changes timeline math, not just pixels/samples.
    """

    id: str
    media: str  # Media.id
    start: int
    src_in: int
    src_out: int
    effects: list[dict[str, Any]] = field(default_factory=list)
    # {"type": "cross_dissolve", "duration_frames": N} or None. When set, this
    # clip's `start` intentionally overlaps the previous clip on its track by
    # duration_frames — see KNOWN_TRANSITION_TYPES and Editor.add_transition.
    transition_in: dict[str, Any] | None = None
    speed: float = 1.0
    # {"x": 0..1, "y": 0..1, "scale": 0..1} or None (= full-frame, the
    # historical default). Only meaningful for a clip on an overlay video
    # track (any video track after the first — see render/ffmpeg.py's
    # z-order convention); the base track always renders full-frame
    # regardless of this field. scale shrinks the clip to that fraction of
    # the canvas (aspect preserved, same fit-then-pad approach as the
    # full-frame case); x/y place the shrunk box's top-left corner as a
    # fraction of the *room it has to move in* (canvas size minus box size),
    # so 0..1 always keeps the whole box on-canvas — see Editor.set_position.
    position: dict[str, Any] | None = None
    # muted: still occupies timeline; render blacks/silences (see ffmpeg export).
    muted: bool = False
    # Optional UI label / color chip (does not affect render).
    name: str | None = None
    color: str | None = None

    @property
    def duration_frames(self) -> int:
        """Source frames consumed (src_out - src_in) — NOT the timeline
        footprint when speed != 1.0. See timeline_duration_frames for that."""
        return self.src_out - self.src_in

    @property
    def timeline_duration_frames(self) -> int:
        """How many frames this clip actually occupies on the timeline."""
        return round(self.duration_frames / self.speed)

    @property
    def end(self) -> int:
        """Timeline frame where this clip ends (exclusive)."""
        return self.start + self.timeline_duration_frames

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "media": self.media,
            "start": self.start,
            "in": self.src_in,
            "out": self.src_out,
            "effects": self.effects,
        }
        if self.transition_in is not None:
            d["transition_in"] = self.transition_in
        if self.speed != 1.0:
            d["speed"] = self.speed
        if self.position is not None:
            d["position"] = self.position
        if self.muted:
            d["muted"] = True
        if self.name:
            d["name"] = self.name
        if self.color:
            d["color"] = self.color
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Clip":
        return cls(
            id=d["id"],
            media=d["media"],
            start=d["start"],
            src_in=d["in"],
            src_out=d["out"],
            effects=d.get("effects", []),
            transition_in=d.get("transition_in"),
            speed=d.get("speed", 1.0),
            position=d.get("position"),
            muted=bool(d.get("muted", False)),
            name=d.get("name"),
            color=d.get("color"),
        )


@dataclass
class Track:
    """``duck`` is a track-level relationship, not a clip effect (ARCHITECTURE.md
    section 5.8's note: ducking "needs a sidechain keyed by a second track").
    When set: {"against": other_audio_track_id, "threshold_db", "ratio",
    "attack_ms", "release_ms", "makeup_db"} — this track's mixed audio is
    compressed whenever the ``against`` track's (pre-duck) signal exceeds the
    threshold. Classic use: a music track ducks against the voiceover track.
    See Editor.set_ducking for validation and render/ffmpeg.py for how it
    compiles to a sidechaincompress keyed by a split of the other track."""

    id: str
    kind: TrackKind
    clips: list[Clip] = field(default_factory=list)
    duck: dict[str, Any] | None = None
    muted: bool = False
    solo: bool = False
    locked: bool = False

    def clips_in_order(self) -> list[Clip]:
        return sorted(self.clips, key=lambda c: c.start)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "clips": [c.to_dict() for c in self.clips],
        }
        if self.duck is not None:
            d["duck"] = self.duck
        if self.muted:
            d["muted"] = True
        if self.solo:
            d["solo"] = True
        if self.locked:
            d["locked"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Track":
        return cls(
            id=d["id"],
            kind=d["kind"],
            clips=[Clip.from_dict(c) for c in d.get("clips", [])],
            duck=d.get("duck"),
            muted=bool(d.get("muted", False)),
            solo=bool(d.get("solo", False)),
            locked=bool(d.get("locked", False)),
        )


@dataclass
class Marker:
    """Timeline marker (chapter / note). Frame is absolute on the project clock."""

    id: str
    frame: int
    label: str = ""
    color: str = "#7c9cff"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "frame": self.frame,
            "label": self.label,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Marker":
        return cls(
            id=d["id"],
            frame=int(d.get("frame", 0)),
            label=str(d.get("label") or ""),
            color=str(d.get("color") or "#7c9cff"),
        )


@dataclass
class Project:
    """Root document. Serialised as ``project.json`` inside a ``.opm`` bundle."""

    id: str = field(default_factory=lambda: new_id("prj"))
    timebase: Timebase = field(default_factory=Timebase)
    resolution: Resolution = field(default_factory=Resolution)
    media: list[Media] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    # Free-text project notes (shown in UI; not burned into export).
    notes: str = ""
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

    def marker_by_id(self, marker_id: str) -> Marker:
        for m in self.markers:
            if m.id == marker_id:
                return m
        raise KeyError(f"no marker with id {marker_id!r}")

    def add_marker(self, frame: int, label: str = "", color: str = "#7c9cff") -> Marker:
        if frame < 0:
            raise ValueError("marker frame must be >= 0")
        m = Marker(new_id("mkr"), int(frame), label=label, color=color)
        self.markers.append(m)
        self.markers.sort(key=lambda x: x.frame)
        return m

    # --- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema": self.schema,
            "id": self.id,
            "timebase": self.timebase.to_dict(),
            "resolution": self.resolution.to_dict(),
            "media": [m.to_dict() for m in self.media],
            "tracks": [t.to_dict() for t in self.tracks],
        }
        if self.markers:
            d["markers"] = [m.to_dict() for m in self.markers]
        if self.notes:
            d["notes"] = self.notes
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        return cls(
            id=d["id"],
            timebase=Timebase.from_dict(d.get("timebase", {})),
            resolution=Resolution.from_dict(d.get("resolution", {})),
            media=[Media.from_dict(m) for m in d.get("media", [])],
            tracks=[Track.from_dict(t) for t in d.get("tracks", [])],
            markers=[Marker.from_dict(m) for m in d.get("markers", [])],
            notes=str(d.get("notes") or ""),
            schema=d.get("schema", SCHEMA_VERSION),
        )
