"""place_pip + set_pip_corner + add_lower_third (0.5.90)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_place_pip_and_lower_third():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pip_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.5, "navy")
        _vid(b, 0.4, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(a, "video", tr.id, 0)
        m = ed.import_media(b, "video")
        r = ed.place_pip(m.id, corner="bottom_right", scale=0.3, start=0)
        assert r["clip_id"]
        assert r["track_id"] != tr.id
        pip = ed._find_clip(r["clip_id"])
        assert pip.position is not None
        assert abs(float(pip.position["scale"]) - 0.3) < 1e-6
        corner = ed.set_pip_corner(r["clip_id"], "top_left", scale=0.25)
        assert corner["corner"] == "top_left"
        l3 = ed.add_lower_third("Test Host", start_frame=0, duration_frames=30)
        assert l3["clip_id"]
        assert any(
            e.get("type") == "text" and "Test Host" in str(e.get("content"))
            for e in (ed._find_clip(l3["clip_id"]).effects or [])
        )
        assert sum(1 for t in ed.project.tracks if t.kind == "video") >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_90():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/place_pip" in app
    assert "/api/edit/lower_third" in app
    assert "def place_pip" in mcp
    assert "def add_lower_third" in mcp
    assert 'id="btn-pip"' in html
    assert "placePipUi" in ts
