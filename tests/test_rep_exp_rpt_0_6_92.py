"""repair_and_export_selection + export_selection_report_pack (0.6.92)."""

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
            "-f", "lavfi", "-i", f"sine=f=630:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_repair_export_and_report_pack():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        rexp = ed.repair_and_export_selection(
            [c.id],
            filename="rep.mp4",
            unlock=True,
            ensure_proxies=False,
            force=False,
            normalize_preset=None,
        )
        assert rexp.get("ok") is True
        assert rexp.get("exported") is True
        assert Path(rexp.get("export_path") or "").is_file()

        pack = ed.export_selection_report_pack([c.id])
        assert Path(pack.get("path") or "").is_dir()
        assert Path(pack.get("meta") or "").is_file()
        assert (Path(pack["path"]) / "selection_checklist.md").is_file()
        assert (Path(pack["path"]) / "validate_selection.json").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_92():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/repair_and_export_selection" in app
    assert "/api/edit/export_selection_report_pack" in app
    assert "def repair_and_export_selection" in mcp
    assert "def export_selection_report_pack" in mcp
    assert 'id="btn-rep-exp-sel"' in html
    assert 'id="btn-report-pack-sel"' in html
    assert "repairAndExportSelectionUi" in ts
    assert "exportSelectionReportPackUi" in ts
