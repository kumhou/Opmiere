"""music_broll one-shot pipeline."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

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


def _wav(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def test_music_broll_pipeline():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mb_"))
    try:
        base = root / "base.mp4"
        a = root / "a.mp4"
        b = root / "b.mp4"
        w = root / "m.wav"
        _vid(base, 3.0, "gray")
        _vid(a, 1.0, "navy")
        _vid(b, 1.0, "maroon")
        _wav(w)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        t0 = ed.add_track("video")
        t1 = ed.add_track("video")
        ed.place_from_file(base, "video", t0.id, 0)
        ma = ed.import_media(a, "video")
        mb = ed.import_media(b, "video")
        ed.import_media(w, "audio")
        fake = {
            "beat_times": [0.0, 1.0, 2.0],
            "bpm_estimate": 60.0,
        }
        with mock.patch("opmiere.ops._detect_beats", return_value=fake):
            r = ed.music_broll(
                t1.id,
                [ma.id, mb.id],
                max_beats=8,
                place_duration_frames=None,
                fit_method="speed",
                transition="cross_dissolve",
                transition_frames=6,
            )
        assert r["markers"]["count"] >= 2
        assert r["place"]["count"] >= 2
        assert r["fit"]["count"] >= 1
        assert len(t1.clips_in_order()) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_54():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/music_broll" in app
    assert "def music_broll" in mcp
    assert 'id="btn-music-broll"' in html
    assert "musicBrollUi" in ts
