"""set_project_resolution + markers_from_blackdetect (0.5.85)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid_with_black(path: Path) -> None:
    # color then black then color
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=0.3",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:d=0.35",
            "-f", "lavfi", "-i", "color=c=maroon:s=160x90:d=0.3",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
    )


def test_set_project_resolution():
    root = Path(tempfile.mkdtemp(prefix="opmiere_res_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=1920, height=1080)
        r = ed.set_project_resolution(1080, 1920)
        assert r["to"]["w"] == 1080
        assert r["to"]["h"] == 1920
        assert ed.project.resolution.w == 1080
        assert ed.project.resolution.h == 1920
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_markers_from_blackdetect():
    root = Path(tempfile.mkdtemp(prefix="opmiere_blk_"))
    try:
        v = root / "v.mp4"
        _vid_with_black(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        r = ed.markers_from_blackdetect(
            clip_id=c.id, min_duration=0.1, pic_th=0.98, pix_th=0.15,
        )
        assert r["detected"] >= 1
        assert r["count"] >= 1
        assert any(m.label.startswith("Black") for m in ed.project.markers)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_85():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/project/resolution" in app
    assert "/api/markers/from_blackdetect" in app
    assert "def set_project_resolution" in mcp
    assert "def markers_from_blackdetect" in mcp
    assert 'id="btn-black"' in html
    assert "blackdetectUi" in ts
