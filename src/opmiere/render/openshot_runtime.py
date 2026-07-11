"""OpenShot / libopenshot runtime via embedded MinGW CPython (S2 sidecar).

Stock Opmiere Python (e.g. 3.10 MSVC) cannot ``import openshot`` — OpenShot's
Windows app ships ``_openshot.pyd`` linked to MinGW ``libpython3.8.dll``.

This module embeds that interpreter in-process with ctypes (same process,
separate Python runtime), then runs small scripts against libopenshot 0.7.x.

Requires a local OpenShot Video Editor install (dev/default path or
``OPMIERE_OPENSHOT_HOME``). Not a user-facing dependency until we vendor.

See docs/SPIKE_LIBOPENSHOT_WINDOWS.md.
"""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "OpenShotRuntime",
    "OpenShotClient",
    "default_openshot_home",
    "openshot_runtime_available",
    "get_openshot_runtime",
]

_DEFAULT_HOMES = (
    Path(r"C:\Program Files\OpenShot Video Editor"),
    Path(r"C:\Program Files (x86)\OpenShot Video Editor"),
)

_lock = threading.RLock()
_singleton: OpenShotRuntime | OpenShotClient | None = None

def default_openshot_home() -> Path | None:
    env = os.environ.get("OPMIERE_OPENSHOT_HOME", "").strip()
    if env:
        p = Path(env)
        if (p / "lib" / "libopenshot.dll").exists() or (p / "lib" / "_openshot.pyd").exists():
            return p
    for p in _DEFAULT_HOMES:
        if (p / "lib" / "libopenshot.dll").exists():
            return p
    return None


def openshot_runtime_available() -> bool:
    return default_openshot_home() is not None


class OpenShotRuntime:
    """Embed OpenShot's MinGW Python once; run libopenshot snippets."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home) if home else default_openshot_home()
        if self.home is None:
            raise RuntimeError(
                "OpenShot install not found. Set OPMIERE_OPENSHOT_HOME or install "
                "OpenShot Video Editor (winget OpenShot.OpenShot)."
            )
        self.libdir = self.home / "lib"
        if not (self.libdir / "libpython3.8.dll").exists():
            raise RuntimeError(f"libpython3.8.dll missing under {self.libdir}")
        if not (self.libdir / "_openshot.pyd").exists():
            raise RuntimeError(f"_openshot.pyd missing under {self.libdir}")
        if not (self.libdir / "library.zip").exists():
            raise RuntimeError(f"library.zip missing under {self.libdir}")
        self._py: Any = None
        self._initialized = False
        self._work = Path(tempfile.mkdtemp(prefix="opmiere_openshot_"))
        self._init_embed()

    def _init_embed(self) -> None:
        home = self.home
        libdir = self.libdir
        # DLL search for Qt/FFmpeg/openshot deps
        os.environ["PATH"] = (
            str(home) + os.pathsep + str(libdir) + os.pathsep + os.environ.get("PATH", "")
        )
        os.environ.setdefault("QT_PLUGIN_PATH", str(home))
        for key in list(os.environ):
            if key.startswith("PYTHON") and key != "PYTHONIOENCODING":
                # do not leak host PYTHONPATH into embed
                if key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
                    del os.environ[key]
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(home))
            os.add_dll_directory(str(libdir))

        zip_path = str(libdir / "library.zip")
        path = zip_path + ";" + str(libdir)

        py = ctypes.PyDLL(str(libdir / "libpython3.8.dll"))
        for flag in ("Py_NoSiteFlag", "Py_IgnoreEnvironmentFlag", "Py_FrozenFlag"):
            if hasattr(py, flag):
                ctypes.c_int.in_dll(py, flag).value = 1

        py.Py_SetPath.argtypes = [ctypes.c_wchar_p]
        py.Py_SetPath(path)
        py.Py_SetPythonHome.argtypes = [ctypes.c_wchar_p]
        py.Py_SetPythonHome(str(libdir))
        py.Py_SetProgramName.argtypes = [ctypes.c_wchar_p]
        py.Py_SetProgramName("opmiere-openshot-runtime")
        py.Py_InitializeEx.argtypes = [ctypes.c_int]
        py.Py_InitializeEx(0)
        if not py.Py_IsInitialized():
            raise RuntimeError("Py_InitializeEx failed for OpenShot libpython3.8")

        py.PyRun_SimpleString.argtypes = [ctypes.c_char_p]
        py.PyRun_SimpleString.restype = ctypes.c_int

        # Bootstrap: put OpenShot lib on sys.path and import openshot once.
        # Silence embed stdout/stderr — C-level prints break pytest capture on Windows.
        boot = f"""
import sys, os
try:
    _devnull = open(os.devnull, "w")
    sys.stdout = _devnull
    sys.stderr = _devnull
except Exception:
    pass
sys.path.insert(0, r"{str(libdir)}")
import openshot
"""
        rc = py.PyRun_SimpleString(boot.encode("utf-8"))
        if rc != 0:
            raise RuntimeError("failed to import openshot inside embedded runtime")

        self._py = py
        self._initialized = True

    def run_script(self, code: str) -> int:
        """Execute Python 3.8 source inside the embed. Returns PyRun_SimpleString code."""
        if not self._initialized or self._py is None:
            raise RuntimeError("runtime not initialized")
        with _lock:
            return int(self._py.PyRun_SimpleString(code.encode("utf-8")))

    def call_json(self, code_body: str) -> dict[str, Any]:
        """Run code that must set ``result`` dict; returns that dict via temp JSON."""
        token = uuid.uuid4().hex
        result_path = self._work / f"result_{token}.json"
        # code_body should assign `result = {...}`
        wrapper = f"""
import json, traceback
result = {{"ok": False, "error": "no result"}}
try:
{ _indent(code_body, 4) }
except Exception as e:
    result = {{"ok": False, "error": repr(e), "traceback": traceback.format_exc()}}
with open(r"{result_path.as_posix()}", "w", encoding="utf-8") as fh:
    json.dump(result, fh)
"""
        rc = self.run_script(wrapper)
        if not result_path.exists():
            return {"ok": False, "error": f"embed produced no result file (rc={rc})"}
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"bad result json: {e}"}
        finally:
            try:
                result_path.unlink(missing_ok=True)
            except OSError:
                pass
        if not isinstance(data, dict):
            return {"ok": False, "error": "result not a dict"}
        return data

    def version(self) -> dict[str, Any]:
        return self.call_json(
            """
result = {
    "ok": True,
    "openshot_version": getattr(openshot, "OPENSHOT_VERSION_FULL", None),
    "backend": "libopenshot",
    "embed": "mingw-python3.8",
}
"""
        )

    def frame_from_media(
        self,
        media_path: str | Path,
        time_seconds: float,
        output_path: str | Path,
        *,
        fps: float | None = None,
    ) -> dict[str, Any]:
        """Seek a media file with FFmpegReader and save one frame (JPG/PNG)."""
        media_path = Path(media_path).resolve()
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not media_path.exists():
            return {"ok": False, "error": f"media not found: {media_path}"}
        # libopenshot Frame.Save reliably writes PNG; convert to jpg on host if needed
        want_jpg = output_path.suffix.lower() in {".jpg", ".jpeg"}
        png_path = output_path.with_suffix(".png") if want_jpg else output_path
        t = max(0.0, float(time_seconds))
        body = f"""
path = r"{media_path.as_posix()}"
outp = r"{png_path.as_posix()}"
t = {t!r}
fps_override = {fps!r}
r = openshot.FFmpegReader(path)
r.Open()
info = r.info
fps_v = fps_override
if fps_v is None:
    fps_v = info.fps.ToFloat() if hasattr(info.fps, "ToFloat") else float(info.fps.num) / float(info.fps.den)
fps_v = float(fps_v) if fps_v and float(fps_v) > 0 else 30.0
# openshot frames are 1-based
frame_num = max(1, int(round(t * fps_v)) + 1)
max_f = int(info.video_length) if int(info.video_length) > 0 else frame_num
if frame_num > max_f:
    frame_num = max_f
f = r.GetFrame(frame_num)
f.Save(outp, 1.0, "PNG")
r.Close()
import os
result = {{
    "ok": os.path.exists(outp) and os.path.getsize(outp) > 32,
    "path": outp,
    "time_seconds": t,
    "frame_number": frame_num,
    "fps": fps_v,
    "width": int(info.width),
    "height": int(info.height),
    "mode": "openshot_ffmpeg_reader",
    "backend": "libopenshot",
    "size": os.path.getsize(outp) if os.path.exists(outp) else 0,
}}
"""
        result = self.call_json(body)
        if result.get("ok") and want_jpg:
            result = self._png_to_jpg(Path(result["path"]), output_path, result)
        return result

    def frame_from_timeline_clip(
        self,
        media_path: str | Path,
        time_seconds: float,
        output_path: str | Path,
        *,
        width: int = 640,
        height: int = 360,
        fps: float = 30.0,
        clip_start: float = 0.0,
        clip_end: float | None = None,
    ) -> dict[str, Any]:
        """Minimal Timeline + one Clip (path-C composite surface for a single shot)."""
        media_path = Path(media_path).resolve()
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not media_path.exists():
            return {"ok": False, "error": f"media not found: {media_path}"}
        want_jpg = output_path.suffix.lower() in {".jpg", ".jpeg"}
        png_path = output_path.with_suffix(".png") if want_jpg else output_path
        t = max(0.0, float(time_seconds))
        w, h = int(width), int(height)
        fps_f = float(fps) if fps > 0 else 30.0
        end_expr = "None" if clip_end is None else repr(float(clip_end))
        body = f"""
path = r"{media_path.as_posix()}"
outp = r"{png_path.as_posix()}"
t = {t!r}
w, h = {w}, {h}
fps_f = {fps_f!r}
clip_start = {float(clip_start)!r}
clip_end = {end_expr}

# Probe duration if end not given
reader = openshot.FFmpegReader(path)
reader.Open()
duration = float(reader.info.duration)
reader.Close()
if clip_end is None or clip_end <= clip_start:
    clip_end = duration

fps_frac = openshot.Fraction(int(round(fps_f)), 1)
layout = openshot.LAYOUT_STEREO
timeline = openshot.Timeline(w, h, fps_frac, 44100, 2, layout)
clip = openshot.Clip(path)
clip.Position(0.0)
clip.Start(clip_start)
clip.End(clip_end)
clip.Layer(1)
timeline.AddClip(clip)
timeline.Open()
frame_num = max(1, int(round(t * fps_f)) + 1)
max_frames = max(1, int(round((clip_end - clip_start) * fps_f)))
if frame_num > max_frames:
    frame_num = max_frames
f = timeline.GetFrame(frame_num)
f.Save(outp, 1.0, "PNG")
timeline.Close()
import os
result = {{
    "ok": os.path.exists(outp) and os.path.getsize(outp) > 32,
    "path": outp,
    "time_seconds": t,
    "frame_number": frame_num,
    "fps": fps_f,
    "width": w,
    "height": h,
    "mode": "openshot_timeline_clip",
    "backend": "libopenshot",
    "size": os.path.getsize(outp) if os.path.exists(outp) else 0,
    "clip_end": clip_end,
}}
"""
        result = self.call_json(body)
        if result.get("ok") and want_jpg:
            result = self._png_to_jpg(Path(result["path"]), output_path, result)
        return result

    def _png_to_jpg(
        self, png_path: Path, jpg_path: Path, result: dict[str, Any],
    ) -> dict[str, Any]:
        import subprocess

        jpg_path = Path(jpg_path)
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(png_path),
                "-q:v", "3",
                str(jpg_path),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and jpg_path.exists() and jpg_path.stat().st_size > 32:
            try:
                png_path.unlink(missing_ok=True)
            except OSError:
                pass
            out = dict(result)
            out["path"] = str(jpg_path.resolve())
            out["size"] = jpg_path.stat().st_size
            return out
        # keep png path if convert failed
        result = dict(result)
        result["jpg_convert_error"] = (proc.stderr or "")[-300:]
        return result

    def close(self) -> None:
        if self._py is not None and self._initialized:
            try:
                if hasattr(self._py, "Py_FinalizeEx"):
                    self._py.Py_FinalizeEx.argtypes = []
                    self._py.Py_FinalizeEx.restype = ctypes.c_int
                    self._py.Py_FinalizeEx()
                elif hasattr(self._py, "Py_Finalize"):
                    self._py.Py_Finalize()
            except Exception:
                pass
            self._initialized = False
            self._py = None


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    lines = text.strip("\n").split("\n")
    return "\n".join(pad + line if line.strip() else line for line in lines)


class OpenShotClient:
    """JSON-lines client to ``python -m opmiere.render.openshot_worker`` (true S2).

    Keeps MinGW embed out of the host process (pytest-safe, isolation).
    """

    def __init__(self) -> None:
        import subprocess
        import sys

        if not openshot_runtime_available():
            raise RuntimeError("OpenShot not installed")
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "opmiere.render.openshot_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        ready = self._readline(timeout_note="ready")
        if not ready.get("ok"):
            self.close()
            raise RuntimeError(ready.get("error") or "worker failed to start")

    def _readline(self, timeout_note: str = "") -> dict[str, Any]:
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            err = ""
            if self._proc.stderr is not None:
                err = self._proc.stderr.read() or ""
            return {
                "ok": False,
                "error": f"worker EOF ({timeout_note}) rc={self._proc.poll()} {err[-500:]}",
            }
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"bad worker line: {e}: {line[:200]}"}

    def _call(self, msg: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            if self._proc.poll() is not None:
                return {"ok": False, "error": f"worker dead rc={self._proc.returncode}"}
            assert self._proc.stdin is not None
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
            return self._readline(timeout_note=msg.get("cmd", "?"))

    def version(self) -> dict[str, Any]:
        return self._call({"cmd": "version"})

    def frame_from_media(
        self,
        media_path: str | Path,
        time_seconds: float,
        output_path: str | Path,
        *,
        fps: float | None = None,
    ) -> dict[str, Any]:
        return self._call({
            "cmd": "frame_media",
            "media_path": str(Path(media_path).resolve()),
            "time_seconds": float(time_seconds),
            "output_path": str(Path(output_path).resolve()),
            "fps": fps,
        })

    def frame_from_timeline_clip(
        self,
        media_path: str | Path,
        time_seconds: float,
        output_path: str | Path,
        *,
        width: int = 640,
        height: int = 360,
        fps: float = 30.0,
        clip_start: float = 0.0,
        clip_end: float | None = None,
    ) -> dict[str, Any]:
        return self._call({
            "cmd": "frame_timeline",
            "media_path": str(Path(media_path).resolve()),
            "time_seconds": float(time_seconds),
            "output_path": str(Path(output_path).resolve()),
            "width": int(width),
            "height": int(height),
            "fps": float(fps),
            "clip_start": float(clip_start),
            "clip_end": clip_end,
        })

    def close(self) -> None:
        try:
            if self._proc.poll() is None and self._proc.stdin:
                self._proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass


def get_openshot_runtime(*, force_new: bool = False) -> OpenShotRuntime | OpenShotClient | None:
    """Process-wide client (subprocess worker by default).

    Set ``OPMIERE_OPENSHOT_INPROCESS=1`` to embed in-host (dev only; breaks some captures).
    """
    global _singleton
    with _lock:
        if force_new and _singleton is not None:
            try:
                _singleton.close()
            except Exception:
                pass
            _singleton = None
        if _singleton is not None:
            return _singleton
        if not openshot_runtime_available():
            return None
        try:
            if os.environ.get("OPMIERE_OPENSHOT_INPROCESS", "").strip() in ("1", "true", "yes"):
                _singleton = OpenShotRuntime()
            else:
                _singleton = OpenShotClient()
        except Exception:
            _singleton = None
            return None
        return _singleton
