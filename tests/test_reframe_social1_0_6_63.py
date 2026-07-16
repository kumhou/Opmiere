"""reframe_selection + export_selection_social (0.6.63)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_reframe_and_social_single():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        rf = ed.reframe_selection(
            [c.id], aspect="9:16", anchor="center", video_only=True,
        )
        assert int(rf.get("count") or 0) >= 1
        assert rf.get("aspect") == "9:16"

        # square is lighter canvas for test speed (same path as reels)
        soc = ed.export_selection_social(
            [c.id], variant="square", filename="sel_sq.mp4",
        )
        p = Path(soc.get("path") or "")
        assert p.is_file()
        assert soc.get("variant") == "square"
        assert int(soc.get("width") or 0) == 1080
        assert int(soc.get("height") or 0) == 1080
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_63():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/reframe_selection" in app
    assert "/api/edit/export_selection_social" in app
    assert "def reframe_selection" in mcp
    assert "def export_selection_social" in mcp
    assert 'id="btn-reframe-sel"' in html
    assert 'id="btn-social1-sel"' in html
    assert "reframeSelectionUi" in ts
    assert "exportSelectionSocialUi" in ts
