"""import_image_sequence + detach_audio_all (0.5.66)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _png(path: Path, color: str = "red") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x36:d=0.04",
            "-frames:v", "1",
            str(path),
        ],
        check=True,
    )


def _vid_av(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(path),
        ],
        check=True,
    )


def test_import_image_sequence_from_dir():
    root = Path(tempfile.mkdtemp(prefix="opmiere_imgseq_"))
    try:
        seq = root / "seq"
        seq.mkdir()
        for i, c in enumerate(["red", "green", "blue", "yellow"]):
            _png(seq / f"frame_{i:04d}.png", c)
        ed = Editor.create(root / "p.opm", fps=10, width=64, height=36)
        tr = ed.add_track("video")
        r = ed.import_image_sequence(seq, fps=10, place_track_id=tr.id, start=0)
        assert r["media_id"]
        assert r.get("clip_id")
        assert r["frame_count"] == 4
        assert ed.project.media_by_id(r["media_id"]).duration_frames >= 3
        assert len(tr.clips) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_detach_audio_all():
    root = Path(tempfile.mkdtemp(prefix="opmiere_detall_"))
    try:
        v = root / "v.mp4"
        _vid_av(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        ed.place_from_file(v, "video", tr.id, c1.end)
        r = ed.detach_audio_all(tr.id, link=True)
        assert r["count"] == 2
        audio_tracks = [t for t in ed.project.tracks if t.kind == "audio"]
        assert audio_tracks
        assert sum(len(t.clips) for t in audio_tracks) == 2
        assert all(c.link_group for c in tr.clips)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_66():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/import/image_sequence" in app
    assert "/api/edit/detach_audio_all" in app
    assert "def import_image_sequence" in mcp
    assert "def detach_audio_all" in mcp
    assert 'id="btn-imgseq"' in html
    assert 'id="btn-detach-all"' in html
    assert "importImageSequenceUi" in ts
