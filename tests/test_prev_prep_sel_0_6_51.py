"""export_selection_preview + prepare_selection_export (0.6.51)."""

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
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_preview_and_prepare():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        # lock then prepare should unlock
        ed.lock_selection_tracks([c.id])
        assert ed.project.track_by_id(tr.id).locked is True
        prep = ed.prepare_selection_export(
            [c.id], unlock_tracks=True, set_work_area=True, pack_gaps=False,
        )
        assert ed.project.track_by_id(tr.id).locked is False
        assert prep["soft_ready"] is True
        assert prep["preflight"]["work_area"]["ready"] is True

        prev = ed.export_selection_preview(
            [c.id], height=90, fps=10,
        )
        assert Path(prev["path"]).is_file()
        assert prev["height"] == 90
        assert prev["selection_span"]["duration_frames"] == 10
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_51():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_preview" in app
    assert "/api/edit/prepare_selection_export" in app
    assert "def export_selection_preview" in mcp
    assert "def prepare_selection_export" in mcp
    assert 'id="btn-prev-sel"' in html
    assert 'id="btn-prep-sel"' in html
    assert "exportSelectionPreviewUi" in ts
    assert "prepareSelectionExportUi" in ts
