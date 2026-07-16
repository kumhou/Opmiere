"""snap_clips_to_markers music-cut workflow."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=2.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_snap_clips_to_markers_nearest():
    root = Path(tempfile.mkdtemp(prefix="opmiere_snapm_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        # clip starts at 0; place second clip off-grid then snap
        c2 = ed.place_from_file(v, "video", tr.id, 40)
        ed.add_marker(frame=30, label="A")
        ed.add_marker(frame=60, label="B")
        # move c2 start to 42 (near 30? nearer 60? 42-30=12, 60-42=18 → 30)
        ed.project.tracks[0].clips_in_order()[1].start = 42
        r = ed.snap_clips_to_markers([c2.id], edge="start", prefer="nearest")
        assert r["count"] == 1
        assert r["clips"][0]["marker_frame"] == 30
        assert ed._find_clip(c2.id).start == 30
        assert c1.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_snap_requires_markers():
    root = Path(tempfile.mkdtemp(prefix="opmiere_snapm2_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        try:
            ed.snap_clips_to_markers([c.id])
            assert False, "expected ValueError"
        except ValueError as e:
            assert "no markers" in str(e).lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_47():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clips/snap_to_markers" in app
    assert "def snap_clips_to_markers" in mcp
    assert 'id="btn-snap-mkr"' in html
    assert "snapSelectionToMarkers" in ts
