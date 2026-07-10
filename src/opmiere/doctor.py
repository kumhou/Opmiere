"""Environment doctor — what an agent/human needs before a real session.

Native packaging companion: install.ps1 puts tools on PATH; doctor says whether
the machine can actually cut film (ffmpeg, Python, optional ASR/scenes/stems,
optional ComfyUI).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__

__all__ = ["run_doctor", "INSTALL_MARKER_NAME"]

INSTALL_MARKER_NAME = "install.json"


def _pkg_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _module_ok(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def _ffmpeg_version(exe: str) -> str | None:
    code, out, err = _run([exe, "-version"])
    if code != 0:
        return None
    line = (out or err).splitlines()[0] if (out or err) else ""
    return line.strip() or "unknown"


def _tcp_open(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def default_install_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Opmiere"
    return Path.home() / ".local" / "share" / "opmiere"


def load_install_marker(root: Path | None = None) -> dict[str, Any] | None:
    root = root or default_install_root()
    p = root / INSTALL_MARKER_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(p), "error": "unreadable"}


def run_doctor(
    *,
    comfy_host: str = "127.0.0.1",
    comfy_port: int = 8188,
    check_comfy: bool = True,
) -> dict[str, Any]:
    """Return a structured health report. ``ok`` is True when core edit works."""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    # Python
    py_ok = sys.version_info >= (3, 10)
    checks.append({
        "id": "python",
        "ok": py_ok,
        "required": True,
        "detail": sys.version.split()[0],
        "executable": sys.executable,
    })
    if not py_ok:
        errors.append("Python >= 3.10 required")

    # Opmiere package
    checks.append({
        "id": "opmiere",
        "ok": True,
        "required": True,
        "detail": __version__,
        "package_version": _pkg_version("opmiere") or __version__,
    })

    # FFmpeg core
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    ff_ver = _ffmpeg_version("ffmpeg") if ffmpeg else None
    fp_ver = _ffmpeg_version("ffprobe") if ffprobe else None
    ff_ok = bool(ffmpeg and ffprobe and ff_ver and fp_ver)
    checks.append({
        "id": "ffmpeg",
        "ok": ff_ok,
        "required": True,
        "ffmpeg_path": ffmpeg,
        "ffprobe_path": ffprobe,
        "ffmpeg_version": ff_ver,
        "ffprobe_version": fp_ver,
    })
    if not ff_ok:
        errors.append(
            "ffmpeg and ffprobe must be on PATH (https://ffmpeg.org/download.html)"
        )

    # mcp
    mcp_ok = _module_ok("mcp")
    checks.append({
        "id": "mcp",
        "ok": mcp_ok,
        "required": True,
        "detail": _pkg_version("mcp") or ("importable" if mcp_ok else "missing"),
    })
    if not mcp_ok:
        errors.append("mcp package missing — pip install -e . or pip install 'mcp[cli]'")

    # Optional extras
    optionals = [
        ("faster_whisper", "transcribe", "faster-whisper", "ASR / captions"),
        ("scenedetect", "scenes", "scenedetect", "PySceneDetect shot cuts"),
        ("demucs", "stems", "demucs", "vocal separation (heavy)"),
        ("fastapi", "web", "fastapi", "opmiere-web GUI"),
        ("uvicorn", "web", "uvicorn", "opmiere-web server"),
        ("PIL", "dev", "pillow", "contact sheet tests / imaging"),
    ]
    for mod, extra, pip_name, purpose in optionals:
        ok = _module_ok(mod)
        checks.append({
            "id": f"optional:{extra}:{mod}",
            "ok": ok,
            "required": False,
            "extra": extra,
            "pip": pip_name,
            "purpose": purpose,
            "version": _pkg_version(pip_name) if ok else None,
        })
        if not ok:
            warnings.append(f"optional [{extra}] not installed — {purpose} ({pip_name})")

    # ComfyUI (generation)
    comfy_ok = False
    if check_comfy:
        comfy_ok = _tcp_open(comfy_host, comfy_port)
        checks.append({
            "id": "comfyui",
            "ok": comfy_ok,
            "required": False,
            "host": comfy_host,
            "port": comfy_port,
            "detail": "reachable" if comfy_ok else "not listening (generation disabled until started)",
        })
        if not comfy_ok:
            warnings.append(
                f"ComfyUI not reachable at {comfy_host}:{comfy_port} — "
                "local generate() will fail until it is running"
            )

    # NVENC encode path
    try:
        from .render.hwencode import encode_status
        enc = encode_status()
        checks.append({
            "id": "nvenc",
            "ok": bool(enc.get("nvenc")),
            "required": False,
            "detail": "h264_nvenc ready" if enc.get("nvenc") else "libx264 software encode",
            "video_encode": enc.get("video_encode"),
        })
        if not enc.get("nvenc"):
            warnings.append(
                "NVENC not available — delivery uses libx264 (slower on large exports)"
            )
    except Exception as e:
        checks.append({
            "id": "nvenc", "ok": False, "required": False, "detail": str(e),
        })

    # Torch / CUDA (informational)
    torch_info: dict[str, Any] = {"ok": _module_ok("torch")}
    if torch_info["ok"]:
        try:
            import torch  # type: ignore
            torch_info["version"] = getattr(torch, "__version__", "?")
            torch_info["cuda_available"] = bool(torch.cuda.is_available())
            if torch_info["cuda_available"]:
                torch_info["device_name"] = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                torch_info["vram_gb"] = round(props.total_memory / (1024 ** 3), 2)
        except Exception as e:
            torch_info["error"] = str(e)
    checks.append({
        "id": "torch",
        "ok": torch_info.get("ok", False),
        "required": False,
        **{k: v for k, v in torch_info.items() if k != "ok"},
        "detail": "optional; used by demucs / some Comfy nodes",
    })

    # Install marker
    marker = load_install_marker()
    checks.append({
        "id": "install_marker",
        "ok": marker is not None and "error" not in (marker or {}),
        "required": False,
        "marker": marker,
        "default_root": str(default_install_root()),
    })

    # Quick ffmpeg round-trip smoke (only if tools present)
    smoke: dict[str, Any] | None = None
    if ff_ok:
        try:
            import tempfile
            with tempfile.TemporaryDirectory(prefix="opmiere_doctor_") as td:
                out = Path(td) / "t.mp4"
                code, _, err = _run(
                    [
                        "ffmpeg", "-y", "-f", "lavfi",
                        "-i", "color=c=black:s=64x36:d=0.2:r=24",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
                    ],
                    timeout=20.0,
                )
                smoke = {
                    "ok": code == 0 and out.exists() and out.stat().st_size > 0,
                    "encode": "libx264 color lavfi",
                }
                if not smoke["ok"]:
                    errors.append(f"ffmpeg encode smoke failed: {err[-400:]}")
                    checks.append({
                        "id": "ffmpeg_smoke",
                        "ok": False,
                        "required": True,
                        "detail": err[-400:],
                    })
                else:
                    checks.append({
                        "id": "ffmpeg_smoke",
                        "ok": True,
                        "required": True,
                        "detail": "libx264 lavfi ok",
                    })
        except Exception as e:
            smoke = {"ok": False, "error": str(e)}
            errors.append(f"ffmpeg smoke error: {e}")

    core_ok = py_ok and ff_ok and mcp_ok and all(
        c["ok"] for c in checks if c.get("required") and c["id"] != "ffmpeg_smoke"
    )
    # include smoke if present
    if any(c["id"] == "ffmpeg_smoke" for c in checks):
        core_ok = core_ok and next(c["ok"] for c in checks if c["id"] == "ffmpeg_smoke")

    return {
        "ok": core_ok,
        "version": __version__,
        "platform": sys.platform,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "smoke": smoke,
        "summary": (
            "core ready — can edit/export with FFmpeg"
            if core_ok
            else "core NOT ready — fix errors before a real session"
        ),
        "agent_note": (
            "If ok=false, do not start a film session. Install ffmpeg, "
            "pip install -e ., re-run opmiere doctor. Optional warnings are fine."
        ),
    }


def format_doctor_text(report: dict[str, Any]) -> str:
    lines = [
        f"Opmiere doctor v{report.get('version')} — {report.get('summary')}",
        f"platform: {report.get('platform')}  ok={report.get('ok')}",
        "",
    ]
    for c in report.get("checks") or []:
        flag = "OK " if c.get("ok") else "FAIL"
        req = "req" if c.get("required") else "opt"
        detail = c.get("detail") or c.get("ffmpeg_version") or c.get("purpose") or ""
        lines.append(f"  [{flag}/{req}] {c.get('id')}: {detail}")
    if report.get("errors"):
        lines.append("")
        lines.append("errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    if report.get("warnings"):
        lines.append("")
        lines.append("warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    return "\n".join(lines) + "\n"
