"""apply_noise_reduction + export_clip_mp4 + add_countdown (0.6.1)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_nr_clip_mp4_countdown():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ncc_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        old_start = c.start
        nr = ed.apply_noise_reduction(c.id, amount=10)
        assert nr["clip_id"] == c.id
        assert any(
            e.get("type") == "noise_reduction"
            for e in (ed._find_clip(c.id).effects or [])
        )
        with ed._mutate():
            ed._find_clip(c.id).effects = []

        cd = ed.add_countdown(seconds=3, frames_per_digit=10)
        assert cd["total_frames"] == 30
        assert len(cd["cards"]) == 3
        assert [x["digit"] for x in cd["cards"]] == [3, 2, 1]
        moved = ed._find_clip(c.id)
        assert moved.start >= old_start + 30

        out = ed.export_clip_mp4(c.id, root / "c.mp4")
        assert Path(out["path"]).exists()
        assert out["clip_id"] == c.id
        assert Path(out["path"]).stat().st_size > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_1():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/noise_reduction" in app
    assert "/api/export/clip_mp4" in app
    assert "/api/edit/countdown" in app
    assert "def apply_noise_reduction" in mcp
    assert "def export_clip_mp4" in mcp
    assert "def add_countdown" in mcp
    assert 'id="btn-nr"' in html
    assert 'id="btn-clip-mp4"' in html
    assert 'id="btn-countdown"' in html
    assert "noiseReductionUi" in ts
    assert "exportClipMp4Ui" in ts
    assert "countdownUi" in ts
