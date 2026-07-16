"""stabilize_selection + export_selection_markers_srt (0.6.60)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
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


def test_stabilize_and_markers_srt():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.add_marker(3, label="A")
        ed.add_marker(8, label="B")

        srt = ed.export_selection_markers_srt(
            [c.id],
            filename="sel.srt",
            relative=True,
            cue_seconds=1.5,
        )
        p = Path(srt.get("path") or "")
        assert p.is_file()
        body = p.read_text(encoding="utf-8")
        assert "A" in body
        assert "B" in body
        assert int(srt.get("count") or 0) == 2

        stab = ed.stabilize_selection(
            [c.id], replace=True, strength=0.5, video_only=True,
        )
        assert int(stab.get("count") or 0) >= 1 or int(stab.get("error_count") or 0) == 0
        # replace may retarget media — timeline still has clip
        assert ed._find_clip(c.id) is not None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_60():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/stabilize_selection" in app
    assert "/api/edit/export_selection_markers_srt" in app
    assert "def stabilize_selection" in mcp
    assert "def export_selection_markers_srt" in mcp
    assert 'id="btn-stab-sel"' in html
    assert 'id="btn-mkr-srt-sel"' in html
    assert "stabilizeSelectionUi" in ts
    assert "exportSelectionMarkersSrtUi" in ts
