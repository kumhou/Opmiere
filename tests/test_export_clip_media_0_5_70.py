"""export_clip_media (0.5.70)."""

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


def test_export_clip_media():
    root = Path(tempfile.mkdtemp(prefix="opmiere_expc_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.6)
        _vid(b, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        out = root / "subs"
        r = ed.export_clip_media(out, track_id=tr.id, container="mp4")
        assert r["count"] == 2
        assert r["error_count"] == 0
        files = list(out.glob("*.mp4"))
        assert len(files) == 2
        # single selection
        r2 = ed.export_clip_media(root / "one", clip_ids=[c1.id])
        assert r2["count"] == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_70():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/clip_media" in app
    assert "def export_clip_media" in mcp
    assert 'id="btn-exp-clips"' in html
    assert "exportClipMediaUi" in ts
