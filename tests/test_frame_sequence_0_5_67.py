"""export_frame_sequence (0.5.67)."""

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
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_export_frame_sequence():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fseq_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        out = root / "frames"
        r = ed.export_frame_sequence(
            out,
            start_frame=0,
            end_frame=4,
            pattern="frame_%06d.png",
            max_frames=4,
            height=90,
        )
        assert r["count"] >= 2
        assert (out / "frame_000001.png").is_file() or any(out.glob("frame_*.png"))
        pngs = list(out.glob("frame_*.png"))
        assert len(pngs) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_67():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/frame_sequence" in app
    assert "def export_frame_sequence" in mcp
    assert 'id="btn-frameseq"' in html
    assert "exportFrameSequenceUi" in ts
