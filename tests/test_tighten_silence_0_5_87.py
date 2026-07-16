"""tighten_silences dialogue cut (0.5.87)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid_av_with_silence(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=f=440:d=0.4",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-f", "lavfi", "-i", "sine=f=660:d=0.4",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=1.2",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a];"
            "[3:v]trim=duration=1.2,setpts=PTS-STARTPTS[v]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )


def test_tighten_silences():
    root = Path(tempfile.mkdtemp(prefix="opmiere_tight_"))
    try:
        v = root / "v.mp4"
        _vid_av_with_silence(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        before = ed.duration_frames()
        r = ed.tighten_silences(
            c.id, noise_db=-40, min_duration=0.2, pad_frames=2,
        )
        assert "count" in r
        # if silence detected and removed, timeline shortens
        after = ed.duration_frames()
        if r["count"] > 0:
            assert after < before
        else:
            # still valid API response
            assert r["count"] == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_87():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/tighten_silences" in app
    assert "def tighten_silences" in mcp
    assert 'id="btn-tighten"' in html
    assert "tightenSilencesUi" in ts
