"""bake_selection + export_selection_cutlist + export_selection_edl (0.6.18)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_bake_cutlist_edl():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bce_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_vignette(c.id, strength=0.4)
        assert any(
            e.get("type") == "vignette"
            for e in (ed._find_clip(c.id).effects or [])
        )
        b = ed.bake_selection([c.id], replace=True, clear_effects=True)
        assert b["count"] == 1
        assert b["error_count"] == 0
        assert not any(
            e.get("type") == "vignette"
            for e in (ed._find_clip(c.id).effects or [])
        )

        cl = ed.export_selection_cutlist(
            [c.id], root / "sel.csv", format="csv",
        )
        assert cl["count"] == 1
        assert Path(cl["path"]).exists()
        text = Path(cl["path"]).read_text(encoding="utf-8")
        assert "clip_id" in text or c.id in text

        edl = ed.export_selection_edl([c.id], root / "sel.edl", title="Test")
        assert edl["count"] == 1
        assert Path(edl["path"]).exists()
        edl_body = Path(edl["path"]).read_text(encoding="utf-8")
        assert "TITLE:" in edl_body
        assert "001" in edl_body
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_18():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/bake_selection" in app
    assert "/api/export/selection_cutlist" in app
    assert "/api/export/selection_edl" in app
    assert "def bake_selection" in mcp
    assert "def export_selection_cutlist" in mcp
    assert "def export_selection_edl" in mcp
    assert 'id="btn-bake-sel"' in html
    assert 'id="btn-cutlist-sel"' in html
    assert 'id="btn-edl-sel"' in html
    assert "bakeSelectionUi" in ts
    assert "exportSelectionCutlistUi" in ts
    assert "exportSelectionEdlUi" in ts
