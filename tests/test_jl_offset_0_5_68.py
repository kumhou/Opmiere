"""set_j_l_offset (0.5.68)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


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


def test_set_j_l_offset():
    root = Path(tempfile.mkdtemp(prefix="opmiere_jl_"))
    try:
        v = root / "v.mp4"
        _vid_av(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 30)
        det = ed.detach_audio(c.id, link=True, audio_start_offset_frames=0)
        assert det["audio_clip_id"]
        r = ed.set_j_l_offset(c.id, -10, relative=False)
        assert r["count"] == 1
        assert r["moved"][0]["to"] == 20  # 30 - 10
        r2 = ed.set_j_l_offset(c.id, 5, relative=True)
        assert r2["moved"][0]["to"] == 25
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_68():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/j_l_offset" in app
    assert "def set_j_l_offset" in mcp
    assert 'id="btn-jl-cut"' in html
    assert "jlOffsetUi" in ts
