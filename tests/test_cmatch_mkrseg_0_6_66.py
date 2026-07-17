"""color_match_selection + export_selection_marker_segments (0.6.66)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, color: str, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_color_match_and_marker_segments():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cm_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, "red", 0.5)
        _vid(b, "blue", 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(b, "video", tr.id, 12, duration_frames=12)

        cm = ed.color_match_selection([c1.id, c2.id], strength=0.5)
        assert cm.get("reference_clip_id") == c1.id
        assert int(cm.get("matched_count") or 0) >= 1

        ed.add_marker(frame=6, label="mid")
        segs = ed.export_selection_marker_segments(
            [c1.id, c2.id],
            include_tail=True,
            min_duration_frames=2,
        )
        assert int(segs.get("count") or 0) >= 1
        assert segs.get("ok") is True
        out = Path(segs.get("output_dir") or "")
        assert out.is_dir()
        for s in segs.get("segments") or []:
            if s.get("ok"):
                assert Path(s["path"]).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_66():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/color_match_selection" in app
    assert "/api/edit/export_selection_marker_segments" in app
    assert "def color_match_selection" in mcp
    assert "def export_selection_marker_segments" in mcp
    assert 'id="btn-cmatch-sel"' in html
    assert 'id="btn-mkr-seg-sel"' in html
    assert "colorMatchSelectionUi" in ts
    assert "exportSelectionMarkerSegmentsUi" in ts
