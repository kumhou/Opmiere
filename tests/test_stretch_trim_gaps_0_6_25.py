"""rate_stretch_selection + trim_selection_edges + selection_gaps (0.6.25)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_stretch_trim_gaps():
    root = Path(tempfile.mkdtemp(prefix="opmiere_stg_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 30)
        c2 = ed.add_clip(tr.id, med.id, 40, 0, 20)

        gaps = ed.selection_gaps([c1.id, c2.id])
        assert gaps["count"] == 1
        assert gaps["gaps"][0]["gap_frames"] == 10

        st = ed.rate_stretch_selection([c1.id], 15)
        assert st["count"] == 1
        assert ed._find_clip(c1.id).timeline_duration_frames == 15
        assert abs(ed._find_clip(c1.id).speed - 2.0) < 1e-6

        # reset for trim: fresh clip
        c3 = ed.add_clip(tr.id, med.id, 80, 0, 20)
        trm = ed.trim_selection_edges([c3.id], head_frames=2, tail_frames=3)
        assert trm["count"] == 1
        c3b = ed._find_clip(c3.id)
        assert c3b.start == 82
        assert c3b.src_in == 2
        assert c3b.src_out == 17
        assert c3b.timeline_duration_frames == 15
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_25():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/rate_stretch_selection" in app
    assert "/api/edit/trim_selection_edges" in app
    assert "/api/edit/selection_gaps" in app
    assert "def rate_stretch_selection" in mcp
    assert "def trim_selection_edges" in mcp
    assert "def selection_gaps" in mcp
    assert 'id="btn-stretch-sel"' in html
    assert 'id="btn-trim-h-sel"' in html
    assert 'id="btn-trim-t-sel"' in html
    assert 'id="btn-gaps-sel"' in html
    assert "rateStretchSelectionUi" in ts
    assert "trimSelectionEdgesUi" in ts
    assert "selectionGapsUi" in ts
