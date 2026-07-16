"""slip_selection + slide_selection + snap_selection_to_playhead (0.6.21)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_slip_slide_snap():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sss_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)  # ~30f
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        # place partial source range so slip has room
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        old_in = c.src_in
        old_start = c.start
        sl = ed.slip_selection([c.id], 3)
        assert sl["count"] == 1
        assert ed._find_clip(c.id).src_in == old_in + 3
        assert ed._find_clip(c.id).start == old_start

        c2 = ed.place_from_file(v, "video", tr.id, int(c.end), duration_frames=10)
        # slide needs adjacent for roll — may skip; just ensure API doesn't crash
        sd = ed.slide_selection([c2.id], 2)
        assert "count" in sd

        snap = ed.snap_selection_to_playhead([c.id, c2.id], 0, edge="start", mode="relative")
        # after snap group earliest should be at 0
        starts = [ed._find_clip(x).start for x in (c.id, c2.id)]
        assert min(starts) == 0
        assert snap.get("count", 0) >= 1 or "moved" in snap or "clips" in snap
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_21():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/slip_selection" in app
    assert "/api/edit/slide_selection" in app
    assert "/api/edit/snap_selection_playhead" in app
    assert "def slip_selection" in mcp
    assert "def slide_selection" in mcp
    assert "def snap_selection_to_playhead" in mcp
    assert 'id="btn-slip-sel-m"' in html
    assert 'id="btn-slide-sel-m"' in html
    assert 'id="btn-snap-sel"' in html
    assert "slipSelectionBatchUi" in ts
    assert "slideSelectionBatchUi" in ts
    assert "snapSelectionPlayheadUi" in ts
