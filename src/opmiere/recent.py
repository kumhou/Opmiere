"""Recent project list (user-local JSON, not inside .opm bundles)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = [
    "recent_path",
    "list_recent",
    "touch_recent",
    "clear_recent",
    "CLIP_COLORS",
]

CLIP_COLORS = [
    "#3d5a80",
    "#2d6a4f",
    "#9b2226",
    "#bb3e03",
    "#0a9396",
    "#8338ec",
    "#ffb703",
    "#6c757d",
]

_MAX = 20


def recent_path() -> Path:
    base = os.environ.get("OPMIERE_CONFIG_DIR")
    if base:
        root = Path(base)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Opmiere"
    else:
        root = Path.home() / ".config" / "opmiere"
    root.mkdir(parents=True, exist_ok=True)
    return root / "recent.json"


def list_recent(*, limit: int = 12) -> dict[str, Any]:
    path = recent_path()
    if not path.exists():
        return {"path": str(path), "projects": [], "count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path), "projects": [], "count": 0}
    items = data.get("projects") or []
    # Drop missing folders
    alive = []
    for it in items:
        p = Path(it.get("path") or "")
        if p.is_dir() and (p / "project.json").exists():
            alive.append(it)
    if len(alive) != len(items):
        _write(alive)
    return {
        "path": str(path),
        "projects": alive[: max(1, int(limit))],
        "count": len(alive),
    }


def touch_recent(bundle_path: Path | str, *, label: str | None = None) -> dict[str, Any]:
    root = Path(bundle_path).resolve()
    items = list_recent(limit=_MAX)["projects"]
    items = [it for it in items if Path(it.get("path") or "").resolve() != root]
    entry = {
        "path": str(root),
        "label": label or root.name,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    items.insert(0, entry)
    _write(items[:_MAX])
    return entry


def clear_recent() -> dict[str, Any]:
    path = recent_path()
    if path.exists():
        path.unlink()
    return {"cleared": True, "path": str(path)}


def _write(items: list[dict[str, Any]]) -> None:
    path = recent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"projects": items}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
