"""selection_levels_report + selection_link_report (0.6.84)."""

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
            "-f", "lavfi", "-i", f"color=c=purple:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=550:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_levels_and_link_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ll_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)

        ed.set_selection_gain([c1.id], -3.0)
        ed.set_selection_opacity([c1.id], 0.8)
        lv = ed.selection_levels_report([c1.id, c2.id])
        assert int(lv.get("count") or 0) == 2
        assert int(lv.get("non_default_count") or 0) >= 1
        row0 = next(r for r in lv["clips"] if r["clip_id"] == c1.id)
        assert abs(float(row0["gain_db"]) + 3.0) < 0.01
        assert abs(float(row0["opacity"]) - 0.8) < 0.01

        # link if API available
        if hasattr(ed, "link_selection"):
            ed.link_selection([c1.id, c2.id])
        lr = ed.selection_link_report([c1.id, c2.id])
        assert int(lr.get("count") or 0) == 2
        assert "clips" in lr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_84():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_levels_report" in app
    assert "/api/edit/selection_link_report" in app
    assert "def selection_levels_report" in mcp
    assert "def selection_link_report" in mcp
    assert 'id="btn-lvl-rep-sel"' in html
    assert 'id="btn-link-rep-sel"' in html
    assert "selectionLevelsReportUi" in ts
    assert "selectionLinkReportUi" in ts
