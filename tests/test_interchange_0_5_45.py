"""Multi-track FCPXML + interchange catalog."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_fcpxml_multi_track_nested_storyline():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fcp_mt_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, "navy")
        _vid(b, "red")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        t0 = ed.add_track("video")
        t1 = ed.add_track("video")
        ed.place_from_file(a, "video", t0.id, 0)
        ed.place_from_file(b, "video", t1.id, 0)
        r = ed.export_fcpxml()
        assert r["count"] == 2
        assert r.get("video_tracks") == 2
        assert "<spine>" in r["body"]
        # nested storyline for overlay track
        assert r["body"].count("asset-clip") >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_interchange_catalog():
    root = Path(tempfile.mkdtemp(prefix="opmiere_xchg_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        cat = ed.interchange_formats()
        exp_ids = {x["id"] for x in cat["export"]}
        imp_ids = {x["id"] for x in cat["import"]}
        assert "otio" in exp_ids and "fcpxml" in exp_ids
        assert "otio" in imp_ids and "fcpxml" in imp_ids
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_45():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/interchange" in app
    assert "def interchange_formats" in mcp
    assert 'id="btn-interchange"' in html
    assert "interchangeCatalogUi" in ts
