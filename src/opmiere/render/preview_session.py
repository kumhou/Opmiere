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


class OpenShotPreviewSession(PreviewSession):
    """Path-C session backed by OpenShot embed runtime (S2)."""

    def __init__(self) -> None:
        from .openshot_runtime import get_openshot_runtime

        self._rt = get_openshot_runtime()
        if self._rt is None:
            raise RuntimeError("OpenShot runtime unavailable")
        self._state = PreviewState.IDLE
        self._project: Project | None = None
        self._bundle: Bundle | None = None
        self._error: str | None = None

    @property
    def backend_name(self) -> str:
        return "libopenshot"

    @property
    def state(self) -> PreviewState:
        return self._state

    def capabilities(self) -> dict[str, Any]:
        ver = {}
        try:
            ver = self._rt.version() if self._rt else {}
        except Exception as e:
            ver = {"error": str(e)}
        return {
            "composite_frame": True,
            "realtime_playback": False,
            "seek": True,
            "backend": self.backend_name,
            "preferred": "libopenshot",
            "fallback": "mlt",
            "interim_scrub": "ffmpeg_proxy",
            "openshot": ver,
            "note": (
                "S2 embed: MinGW libpython from OpenShot install. "
                "Timeline multi-clip mapping still incremental."
            ),
        }

    def open(self, project: Project, bundle: Bundle) -> dict[str, Any]:
        self._project = project
        self._bundle = bundle
        self._state = PreviewState.IDLE
        self._error = None
        return {
            "ok": True,
            "state": self.state.value,
            "backend": self.backend_name,
            "agent_note": "OpenShot session open; use frame_at for engine frames.",
        }

    def close(self) -> None:
        self._project = None
        self._bundle = None
        self._state = PreviewState.IDLE

    def seek(self, time_seconds: float) -> dict[str, Any]:
        self._state = PreviewState.SEEKING
        self._state = PreviewState.IDLE
        return {"ok": True, "state": self.state.value, "time_seconds": float(time_seconds)}

    def play(self) -> dict[str, Any]:
        # Realtime play loop not wired yet — transport still proxy/UI side
        self._state = PreviewState.PLAYING
        return {
            "ok": False,
            "state": self.state.value,
            "error": "realtime play not implemented; use frame_at / proxy play",
        }

    def pause(self) -> dict[str, Any]:
        self._state = PreviewState.IDLE
        return {"ok": True, "state": self.state.value}

    def frame_at(
        self,
        time_seconds: float,
        output_path: Path,
        *,
        height: int = 360,
    ) -> dict[str, Any]:
        """Engine frame: base-track media via Timeline+Clip when project open."""
        self._state = PreviewState.SEEKING
        try:
            if self._project is None or self._bundle is None:
                return {
                    "ok": False,
                    "error": "session not open — call open(project, bundle) first",
                    "state": self.state.value,
                }
            from .openshot_map import build_openshot_plan

            plan = build_openshot_plan(
                self._project, self._bundle, height=height,
            )
            if plan.get("clip_count", 0) <= 0:
                self._state = PreviewState.ERROR
                return {
                    "ok": False,
                    "error": "no video clips in plan",
                    "state": self.state.value,
                }
            r = self._rt.frame_from_project(
                plan, float(time_seconds), Path(output_path),
            )
            self._state = PreviewState.IDLE if r.get("ok") else PreviewState.ERROR
            r["state"] = self.state.value
            r["plan_clip_count"] = plan.get("clip_count")
            return r
        except Exception as e:
            self._state = PreviewState.ERROR
            self._error = str(e)
            return {"ok": False, "error": str(e), "state": self.state.value}


def preview_engine_status() -> dict[str, Any]:
    """Doctor / MCP: what interactive engine is available right now."""
    import importlib.util

    from .openshot_runtime import openshot_runtime_available, default_openshot_home

    openshot_mod = importlib.util.find_spec("openshot") is not None
    home = default_openshot_home()
    session = get_preview_session()
    return {
        "active_backend": session.backend_name,
        "state": session.state.value,
        "capabilities": session.capabilities(),
        "import_openshot_host": openshot_mod,
        "openshot_app_present": home is not None,
        "openshot_home": str(home) if home else None,
        "spike": "docs/SPIKE_LIBOPENSHOT_WINDOWS.md",
        "adr": "docs/ADR_UI_AND_PREVIEW.md",
        "agent_note": (
            "path C: libopenshot via OpenShot install embed when available; "
            "else unavailable. Interim scrub remains FFmpeg proxy."
        ),
    }


def get_preview_session() -> PreviewSession:
    """Factory: OpenShot embed when install present; else unavailable stub."""
    from .openshot_runtime import openshot_runtime_available

    if openshot_runtime_available():
        try:
            return OpenShotPreviewSession()
        except Exception:
            return UnavailablePreviewSession()
    return UnavailablePreviewSession()
