"""add_solid + export_work_area_gif (0.5.94)."""

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


def test_solid_and_work_area_gif():
    root = Path(tempfile.mkdtemp(prefix="opmiere_solid_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        s = ed.add_solid("#ff0000", duration_frames=20, append=True)
        assert s["clip_id"]
        clip = ed._find_clip(s["clip_id"])
        assert clip.timeline_duration_frames == 20
        # cache reuse (append after solid, no overlap)
        s2 = ed.add_solid("#ff0000", duration_frames=10, append=True)
        assert s2["media_id"] == s["media_id"]
        assert s2["start"] >= s["start"] + 20 - 1

        # work area gif needs in/out
        ed.set_in_point(0)
        ed.set_out_point(10)
        gif = ed.export_work_area_gif(root / "wa.gif", fps=8, width=100)
        assert Path(gif["path"]).exists()
        assert gif["bytes"] > 0
        assert gif["in_frame"] == 0
        assert gif["out_frame"] == 10
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_94():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/solid" in app
    assert "/api/export/work_area_gif" in app
    assert "def add_solid" in mcp
    assert "def export_work_area_gif" in mcp
    assert 'id="btn-solid"' in html
    assert 'id="btn-wa-gif"' in html
    assert "solidUi" in ts
    assert "exportWorkAreaGifUi" in ts
