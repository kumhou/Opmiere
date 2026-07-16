"""add_grade_layer (0.5.74)."""

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


def test_add_grade_layer():
    root = Path(tempfile.mkdtemp(prefix="opmiere_grade_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        r = ed.add_grade_layer(
            [{"type": "color", "brightness": 0.1, "contrast": 1.1, "saturation": 1.0}],
            start=0,
            end=None,
        )
        assert r["clip_id"]
        assert r["track_id"] != tr.id
        assert "color" in r["effects"]
        # two video tracks
        assert sum(1 for t in ed.project.tracks if t.kind == "video") >= 2
        grade_tr = ed.project.track_by_id(r["track_id"])
        assert grade_tr.clips
        assert any(
            e.get("type") == "color"
            for e in grade_tr.clips[0].effects or []
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_74():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/grade_layer" in app
    assert "def add_grade_layer" in mcp
    assert 'id="btn-grade-layer"' in html
    assert "gradeLayerUi" in ts
