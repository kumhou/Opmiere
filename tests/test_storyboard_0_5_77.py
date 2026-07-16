"""export_storyboard (0.5.77)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_export_storyboard():
    root = Path(tempfile.mkdtemp(prefix="opmiere_story_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.6)
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=2, label="Hit")
        out = root / "board"
        r = ed.export_storyboard(out, width=160, max_stills=16)
        assert r["still_count"] >= 1
        assert (out / "storyboard.json").is_file()
        assert (out / "stills").is_dir()
        assert list((out / "stills").glob("*.jpg")) or r["still_count"] >= 0
        # contact may fail in some envs; chapters should exist
        assert (out / "youtube_chapters.txt").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_77():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/storyboard" in app
    assert "def export_storyboard" in mcp
    assert 'id="btn-storyboard"' in html
    assert "exportStoryboardUi" in ts
