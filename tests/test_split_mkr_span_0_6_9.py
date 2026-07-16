"""split_selection_at + markers_from_selection + selection_span (0.6.9)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_split_markers_span():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sms_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        span = ed.selection_span([c.id])
        assert span["start_frame"] == c.start
        assert span["end_frame"] == c.end
        assert span["duration_frames"] == c.timeline_duration_frames

        mid = c.start + c.timeline_duration_frames // 2
        sp = ed.split_selection_at([c.id], mid)
        assert sp["count"] == 1
        left_id = sp["splits"][0]["left_id"]
        right_id = sp["splits"][0]["right_id"]
        assert ed._find_clip(left_id).end == mid
        assert ed._find_clip(right_id).start == mid

        mk = ed.markers_from_selection([left_id, right_id], edge="start")
        assert mk["count"] == 2
        frames = sorted(m["frame"] for m in mk["markers"])
        assert frames[0] == ed._find_clip(left_id).start
        assert frames[1] == ed._find_clip(right_id).start
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_9():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/split_selection" in app
    assert "/api/markers/from_selection" in app
    assert "/api/edit/selection_span" in app
    assert "def split_selection_at" in mcp
    assert "def markers_from_selection" in mcp
    assert "def selection_span" in mcp
    assert 'id="btn-split-sel"' in html
    assert 'id="btn-mkr-sel"' in html
    assert 'id="btn-span-sel"' in html
    assert "splitSelectionUi" in ts
    assert "markersFromSelectionUi" in ts
    assert "selectionSpanUi" in ts
