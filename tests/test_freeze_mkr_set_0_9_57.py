"""freeze_selection_set_at + markers_from_selection_set (0.9.57)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_freeze_and_markers_from_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_frzmkr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        fr = ed.freeze_selection_set_at(
            "hero", timeline_frame=3, duration_frames=6,
        )
        assert fr.get("selection_set") == "hero"
        assert fr.get("timeline_frame") == 3
        assert "count" in fr

        mk = ed.markers_from_selection_set("hero", edge="start", prefix="Sel ")
        assert mk.get("selection_set") == "hero"
        assert mk.get("edge") == "start"
        assert int(mk.get("count") or 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_57():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/freeze_selection_set_at" in app
    assert "/api/edit/markers_from_selection_set" in app
    assert "def freeze_selection_set_at" in mcp
    assert "def markers_from_selection_set" in mcp
    assert 'id="btn-freeze-set"' in html
    assert 'id="btn-mkr-from-set"' in html
    assert "freezeSelectionSetAtUi" in ts
    assert "markersFromSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "freeze_selection_set_at" in cat["tool_ids"]
    assert "markers_from_selection_set" in cat["tool_ids"]
