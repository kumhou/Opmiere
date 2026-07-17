"""export selection sets status/validate reports (0.7.8)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=yellow:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=150:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_status_and_validate_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rpt_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        ed.save_selection_set("hero", [c.id])

        st = ed.export_selection_sets_status_report(
            validate=True, write_markdown=True,
        )
        assert Path(st["path"]).is_file()
        assert Path(st["markdown_path"]).is_file()
        data = json.loads(Path(st["path"]).read_text(encoding="utf-8"))
        assert data.get("schema") == "opmiere.selection_sets_status_report.v1"
        assert data.get("count") == 1

        vr = ed.export_selection_sets_validate_report(write_markdown=True)
        assert Path(vr["path"]).is_file()
        assert Path(vr["markdown_path"]).is_file()
        vdata = json.loads(Path(vr["path"]).read_text(encoding="utf-8"))
        assert vdata.get("schema") == "opmiere.selection_sets_validate_report.v1"
        assert vdata.get("count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_8():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_sets_status_report" in app
    assert "/api/edit/export_selection_sets_validate_report" in app
    assert "def export_selection_sets_status_report" in mcp
    assert "def export_selection_sets_validate_report" in mcp
    assert 'id="btn-stat-rpt-set"' in html
    assert 'id="btn-val-rpt-set"' in html
    assert "exportSelectionSetsStatusReportUi" in ts
    assert "exportSelectionSetsValidateReportUi" in ts
