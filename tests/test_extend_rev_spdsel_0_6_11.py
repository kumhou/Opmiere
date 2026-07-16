"""extend_to_next_clip + reverse_selection + set_selection_speed_ripple (0.6.11)."""

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


def test_extend_reverse_speed_sel():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ers_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)  # ~30f
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        # place short then later clip leaving a gap, with source headroom
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 25, duration_frames=10)
        assert c2.start > c1.end
        ext = ed.extend_to_next_clip(c1.id)
        assert ext["extended_frames"] > 0
        assert ed._find_clip(c1.id).end == c2.start or ext["extended_frames"] <= (
            c2.start - 10
        )

        # reverse on overlay track so re-encode doesn't fight base contiguity tests
        over = ed.add_track("video")
        rclip = ed.place_from_file(v, "video", over.id, 0, duration_frames=8)
        rev = ed.reverse_selection([rclip.id])
        assert rev["count"] == 1
        assert rev["error_count"] == 0

        # speed ripple on last base clip
        c2b = ed._find_clip(c2.id)
        old_dur = c2b.timeline_duration_frames
        spd = ed.set_selection_speed_ripple([c2.id], 2.0)
        assert spd["count"] == 1
        assert ed._find_clip(c2.id).timeline_duration_frames < old_dur
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_11():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/extend_to_next" in app
    assert "/api/edit/reverse_selection" in app
    assert "/api/edit/selection_speed_ripple" in app
    assert "def extend_to_next_clip" in mcp
    assert "def reverse_selection" in mcp
    assert "def set_selection_speed_ripple" in mcp
    assert 'id="btn-ext-next"' in html
    assert 'id="btn-rev-sel"' in html
    assert 'id="btn-spd2-sel"' in html
    assert "extendToNextUi" in ts
    assert "reverseSelectionUi" in ts
    assert "selectionSpeedRippleUi" in ts
