"""PreviewSession — interactive preview contract (path C).

See docs/ADR_UI_AND_PREVIEW.md and docs/SPIKE_LIBOPENSHOT_WINDOWS.md.

Product path: true NLE engine (prefer libopenshot; MLT fallback). Packaging is
not ready on stock CPython — this module freezes the *API* so Tauri/MCP/shell
can bind without waiting on wheels.

States: unavailable | idle | seeking | playing | error
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any

from ..bundle import Bundle
from ..model import Project

__all__ = [
    "PreviewState",
    "PreviewSession",
    "UnavailablePreviewSession",
    "get_preview_session",
    "preview_engine_status",
]


class PreviewState(str, Enum):
    UNAVAILABLE = "unavailable"
    IDLE = "idle"
    SEEKING = "seeking"
    PLAYING = "playing"
    ERROR = "error"


class PreviewSession(ABC):
    """One open interactive preview for a project (engine-agnostic)."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def state(self) -> PreviewState:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def open(self, project: Project, bundle: Bundle) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def seek(self, time_seconds: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def play(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def pause(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def frame_at(
        self,
        time_seconds: float,
        output_path: Path,
        *,
        height: int = 360,
    ) -> dict[str, Any]:
        """Composite frame at t → image path. Engines may no-op when unavailable."""
        raise NotImplementedError


class UnavailablePreviewSession(PreviewSession):
    """Default until libopenshot sidecar/wheel or MLT adapter ships."""

    def __init__(self) -> None:
        self._state = PreviewState.UNAVAILABLE
        self._error: str | None = (
            "Interactive engine not packaged for this Python. "
            "See docs/SPIKE_LIBOPENSHOT_WINDOWS.md (prefer openshot S1/S2; MLT S3)."
        )

    @property
    def backend_name(self) -> str:
        return "none"

    @property
    def state(self) -> PreviewState:
        return self._state

    def capabilities(self) -> dict[str, Any]:
        return {
            "composite_frame": False,
            "realtime_playback": False,
            "seek": False,
            "backend": self.backend_name,
            "preferred": "libopenshot",
            "fallback": "mlt",
            "interim_scrub": "ffmpeg_proxy",
            "note": self._error,
        }

    def open(self, project: Project, bundle: Bundle) -> dict[str, Any]:
        return {
            "ok": False,
            "state": self.state.value,
            "backend": self.backend_name,
            "error": self._error,
            "agent_note": (
                "Use ensure_preview_proxy / frame_at for interim eyes. "
                "Do not claim realtime interactive preview."
            ),
        }

    def close(self) -> None:
        self._state = PreviewState.UNAVAILABLE

    def seek(self, time_seconds: float) -> dict[str, Any]:
        return {
            "ok": False,
            "state": self.state.value,
            "time_seconds": float(time_seconds),
            "error": self._error,
        }

    def play(self) -> dict[str, Any]:
        return {
            "ok": False,
            "state": self.state.value,
            "error": self._error,
        }

    def pause(self) -> dict[str, Any]:
        return {
            "ok": False,
            "state": self.state.value,
            "error": self._error,
        }

    def frame_at(
        self,
        time_seconds: float,
        output_path: Path,
        *,
        height: int = 360,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "path": None,
            "time_seconds": float(time_seconds),
            "height": int(height),
            "state": self.state.value,
            "error": self._error,
            "agent_note": "Call Editor.frame_at / ensure_preview_proxy instead until engine ships.",
        }


def preview_engine_status() -> dict[str, Any]:
    """Doctor / MCP: what interactive engine is available right now."""
    import importlib.util

    openshot_mod = importlib.util.find_spec("openshot") is not None
    # Optional: detect OpenShot app install (dev machine only)
    openshot_app = Path(r"C:\Program Files\OpenShot Video Editor\lib\libopenshot.dll")
    app_dll = openshot_app.exists()
    session = get_preview_session()
    return {
        "active_backend": session.backend_name,
        "state": session.state.value,
        "capabilities": session.capabilities(),
        "import_openshot": openshot_mod,
        "openshot_app_dll_present": app_dll,
        "spike": "docs/SPIKE_LIBOPENSHOT_WINDOWS.md",
        "adr": "docs/ADR_UI_AND_PREVIEW.md",
        "agent_note": (
            "path C packaging not ready on stock CPython — "
            "interim scrub remains FFmpeg proxy; product GUI is Tauri later."
        ),
    }


def get_preview_session() -> PreviewSession:
    """Factory: returns real engine when registered; else unavailable stub."""
    # Future: try OpenShotPreviewSession / MltPreviewSession registration.
    return UnavailablePreviewSession()
