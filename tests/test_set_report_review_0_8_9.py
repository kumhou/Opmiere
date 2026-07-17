"""export_selection_set_report_pack + review_package (0.8.9)."""

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
            "-f", "lavfi", "-i", f"color=c=darkgreen:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=150:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_report_and_review_packages():
    root = Path(tempfile.mkdtemp(prefix="opmiere_srr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        rpt = ed.export_selection_set_report_pack("hero")
        assert rpt.get("ok") is True
        assert rpt.get("selection_set") == "hero"
        assert Path(rpt["out_dir"]).is_dir()

        rev = ed.export_selection_set_review_package(
            "hero",
            include_handoff=True,
            include_storyboard=True,
            include_export=False,
            include_social=False,
        )
        assert rev.get("ok") is True
        assert rev.get("selection_set") == "hero"
        assert Path(rev["out_dir"]).is_dir()
        assert rev.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_9():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_report_pack" in app
    assert "/api/edit/export_selection_set_review_package" in app
    assert "def export_selection_set_report_pack" in mcp
    assert "def export_selection_set_review_package" in mcp
    assert 'id="btn-set-reports"' in html
    assert 'id="btn-set-review"' in html
    assert "exportSelectionSetReportPackUi" in ts
    assert "exportSelectionSetReviewPackageUi" in ts
