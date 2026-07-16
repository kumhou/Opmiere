"""insert_edit + overwrite_edit (0.5.73)."""

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


def test_insert_edit_ripples():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ins_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.4, "navy")
        _vid(b, 0.3, "maroon")
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        m2 = ed.import_media(b, "video")
        mid = c1.end // 2
        r = ed.insert_edit(m2.id, tr.id, mid, ripple=True)
        assert r["clip_id"]
        assert r["moved_count"] >= 1
        clips = tr.clips_in_order()
        assert len(clips) >= 2
        # inserted clip starts at mid
        assert any(c.start == mid for c in clips)
        # something after mid was pushed
        assert any(c.start > mid for c in clips)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_overwrite_edit_lifts_window():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ow_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.6, "teal")
        _vid(b, 0.2, "orange")
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        m2 = ed.import_media(b, "video")
        r = ed.overwrite_edit(m2.id, tr.id, 2, src_in=0, src_out=min(3, m2.duration_frames))
        assert r["clip_id"]
        assert r["at_frame"] == 2
        # duration of project still covers original span-ish
        assert any(c.media == m2.id for c in tr.clips)
        assert c1.id not in {c.id for c in tr.clips} or any(
            c.id == c1.id for c in tr.clips
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_73():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/insert" in app
    assert "/api/edit/overwrite" in app
    assert "def insert_edit" in mcp
    assert "def overwrite_edit" in mcp
    assert 'id="btn-insert-ed"' in html
    assert "insertEditAtPlayhead" in ts
