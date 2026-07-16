"""three_point_edit + media_usage_report (0.5.75)."""

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


def test_three_point_overwrite_stretch():
    root = Path(tempfile.mkdtemp(prefix="opmiere_3pt_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.8, "navy")
        _vid(b, 0.4, "maroon")
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(a, "video", tr.id, 0)
        m = ed.import_media(b, "video")
        ed.set_in_point(2)
        ed.set_out_point(8)
        r = ed.three_point_edit(m.id, tr.id, mode="overwrite", fit="stretch")
        assert r["clip_id"]
        assert r["dest_duration"] == 6
        clip = ed._find_clip(r["clip_id"])
        assert abs(clip.timeline_duration_frames - 6) <= 1
        assert clip.start == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_media_usage_report():
    root = Path(tempfile.mkdtemp(prefix="opmiere_usage_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.4)
        _vid(b, 0.3)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(a, "video", tr.id, 0)
        ed.import_media(b, "video")  # unused
        r = ed.media_usage_report()
        assert r["count"] == 2
        assert r["used_count"] == 1
        assert r["unused_count"] == 1
        assert len(r["unused_ids"]) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_75():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/three_point" in app
    assert "/api/media/usage" in app
    assert "def three_point_edit" in mcp
    assert "def media_usage_report" in mcp
    assert 'id="btn-3pt"' in html
    assert "threePointEditUi" in ts
