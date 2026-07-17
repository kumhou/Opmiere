"""clear_selection_set_watermarks + trim_selection_set_edges (0.9.64)."""

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


def test_clear_wm_and_trim_edges_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_clrwm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])
        ed.watermark_selection_set("hero", "DRAFT")

        wm = ed.clear_selection_set_watermarks("hero")
        assert wm.get("selection_set") == "hero"
        assert int(wm.get("count") or 0) >= 1

        trm = ed.trim_selection_set_edges(
            "hero", head_frames=0, tail_frames=1,
        )
        assert trm.get("selection_set") == "hero"
        assert "count" in trm
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_64():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/clear_selection_set_watermarks" in app
    assert "/api/edit/trim_selection_set_edges" in app
    assert "def clear_selection_set_watermarks" in mcp
    assert "def trim_selection_set_edges" in mcp
    assert 'id="btn-clr-wm-set"' in html
    assert 'id="btn-trim-edges-set"' in html
    assert "clearSelectionSetWatermarksUi" in ts
    assert "trimSelectionSetEdgesUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "clear_selection_set_watermarks" in cat["tool_ids"]
    assert "trim_selection_set_edges" in cat["tool_ids"]
