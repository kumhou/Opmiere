"""place_media_at_markers B-roll grid."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_place_media_at_markers_grid():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pam_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        base = root / "base.mp4"
        _vid(a, 1.0, "navy")
        _vid(b, 1.0, "maroon")
        _vid(base, 3.0, "gray")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        t0 = ed.add_track("video")
        t1 = ed.add_track("video")
        ed.place_from_file(base, "video", t0.id, 0)
        ma = ed.import_media(a, "video")
        mb = ed.import_media(b, "video")
        ed.add_marker(frame=0, label="B1")
        ed.add_marker(frame=30, label="B2")
        ed.add_marker(frame=60, label="B3")
        r = ed.place_media_at_markers(
            [ma.id, mb.id],
            t1.id,
            duration_frames=15,
            mode="overwrite",
            cycle=True,
        )
        assert r["count"] == 3
        clips = t1.clips_in_order()
        assert len(clips) == 3
        assert clips[0].start == 0
        assert clips[1].start == 30
        assert clips[2].start == 60
        # cycle: a, b, a
        assert clips[0].media == ma.id
        assert clips[1].media == mb.id
        assert clips[2].media == ma.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_place_requires_markers():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pam2_"))
    try:
        a = root / "a.mp4"
        _vid(a)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        m = ed.import_media(a, "video")
        try:
            ed.place_media_at_markers([m.id], tr.id)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "no markers" in str(e).lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_51():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/place/at_markers" in app
    assert "def place_media_at_markers" in mcp
    assert 'id="btn-place-mkr"' in html
    assert "placeAtMarkersUi" in ts
