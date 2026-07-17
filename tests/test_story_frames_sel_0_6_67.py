"""export_selection_storyboard + export_selection_frame_sequence (0.6.67)."""

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
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=500:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_storyboard_and_frames():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.add_marker(frame=3, label="hit")

        sb = ed.export_selection_storyboard(
            [c.id], include_contact=True, max_stills=8, width=160,
        )
        assert int(sb.get("still_count") or 0) >= 1
        assert Path(sb.get("path") or "").is_dir()
        assert (Path(sb["path"]) / "storyboard.json").is_file()

        fr = ed.export_selection_frame_sequence(
            [c.id], max_frames=4, height=90,
        )
        out = Path(fr.get("path") or "")
        assert out.is_dir()
        pngs = list(out.glob("*.png"))
        assert len(pngs) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_67():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_storyboard" in app
    assert "/api/edit/export_selection_frame_sequence" in app
    assert "def export_selection_storyboard" in mcp
    assert "def export_selection_frame_sequence" in mcp
    assert 'id="btn-story-sel"' in html
    assert 'id="btn-frames-sel"' in html
    assert "exportSelectionStoryboardUi" in ts
    assert "exportSelectionFrameSequenceUi" in ts
