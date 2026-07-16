"""beat_grid one-shot music edit."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from opmiere import Editor


def _vid(path: Path, d: float = 3.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _wav(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def test_beat_grid_markers_and_both():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bg_"))
    try:
        v = root / "v.mp4"
        w = root / "m.wav"
        _vid(v, 3.0)
        _wav(w)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.import_media(w, "audio")
        fake = {"beat_times": [0.5, 1.0, 1.5, 2.0], "bpm_estimate": 120.0}
        with mock.patch("opmiere.ops._detect_beats", return_value=fake):
            r = ed.beat_grid(mode="markers", clear_existing_prefix=True)
        assert r["markers"]["count"] == 4
        assert len(ed.project.markers) == 4

        with mock.patch("opmiere.ops._detect_beats", return_value=fake):
            r2 = ed.beat_grid(
                track_id=tr.id, mode="both", clear_existing_prefix=True,
            )
        assert r2["markers"]["count"] >= 1
        assert r2["split"]["count"] >= 1
        # long clip should be sliced
        assert len(ed.project.tracks[0].clips) > 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_beat_grid_markers_snap():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bg2_"))
    try:
        v = root / "v.mp4"
        w = root / "m.wav"
        _vid(v, 2.0)
        _wav(w)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.project.tracks[0].clips[0].start = 40
        ed.import_media(w, "audio")
        fake = {"beat_times": [1.0, 2.0], "bpm_estimate": 60.0}  # frames 30, 60
        with mock.patch("opmiere.ops._detect_beats", return_value=fake):
            r = ed.beat_grid(
                mode="markers_snap",
                snap_clip_ids=[c.id],
                clear_existing_prefix=True,
            )
        assert r["snap"]["count"] == 1
        assert ed._find_clip(c.id).start == 30
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_48():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/beat_grid" in app
    assert "def beat_grid" in mcp
    assert 'id="btn-beat-grid"' in html
    assert "beatGridUi" in ts
