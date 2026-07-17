"""selection_position_report + selection_meta_report (0.6.85)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=560:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_position_and_meta_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pm_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        ed.set_selection_meta([c.id], name="Hero", color="#00ffaa")
        mr = ed.selection_meta_report([c.id])
        assert int(mr.get("count") or 0) == 1
        assert int(mr.get("named_count") or 0) == 1
        assert mr["clips"][0]["name"] == "Hero"

        pr = ed.selection_position_report([c.id])
        assert int(pr.get("count") or 0) == 1
        assert "with_position" in pr
        # default full-frame: usually no position
        assert pr["clips"][0]["clip_id"] == c.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_85():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_position_report" in app
    assert "/api/edit/selection_meta_report" in app
    assert "def selection_position_report" in mcp
    assert "def selection_meta_report" in mcp
    assert 'id="btn-pos-rep-sel"' in html
    assert 'id="btn-meta-rep-sel"' in html
    assert "selectionPositionReportUi" in ts
    assert "selectionMetaReportUi" in ts
