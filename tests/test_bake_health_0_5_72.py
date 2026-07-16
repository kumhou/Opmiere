"""bake_clip + project_health_report (0.5.72)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_bake_clip_replaces_and_clears_fx():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bake_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "blur", "amount": 2.0})
        ed.set_clip_flip(c.id, horizontal=True)
        old_media = c.media
        r = ed.bake_clip(c.id, replace=True, clear_effects=True)
        assert r["replaced"] is True
        assert r["effects_cleared"] is True
        assert r["media_id"] != old_media
        assert c.media == r["media_id"]
        assert not c.effects
        assert c.src_in == 0
        assert c.speed == 1.0
        assert ed.bundle.media_path(
            ed.project.media_by_id(r["media_id"]).path
        ).exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_project_health_report():
    root = Path(tempfile.mkdtemp(prefix="opmiere_health_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        r = ed.project_health_report()
        assert "preflight" in r
        assert "gaps" in r
        assert "unused" in r
        assert "path_c" in r
        assert "stats" in r
        assert "ready" in r
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_72():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/bake" in app
    assert "/api/project/health" in app
    assert "def bake_clip" in mcp
    assert "def project_health_report" in mcp
    assert 'id="btn-bake"' in html
    assert "bakeSelectionUi" in ts
    assert "projectHealthUi" in ts
