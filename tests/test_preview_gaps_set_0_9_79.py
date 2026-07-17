"""export_selection_set_preview + selection_set_gaps (0.9.79)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_preview_and_gaps_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_prgaps_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        # contiguous for full-timeline preview export path
        c0 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("tight", [c0.id])
        prev = ed.export_selection_set_preview(
            "tight",
            height=180,
            fps=8.0,
        )
        assert prev.get("selection_set") == "tight"
        path = prev.get("path") or prev.get("output_path")
        assert path and Path(str(path)).is_file()

        # gap set: report only (preview needs contiguous timeline)
        tr2 = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr2.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr2.id, 12, duration_frames=8)
        ed.save_selection_set("gappy", [c1.id, c2.id])
        gaps = ed.selection_set_gaps("gappy")
        assert gaps.get("selection_set") == "gappy"
        assert gaps.get("count", 0) >= 1
        assert gaps.get("clip_count") == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_79():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_preview" in app
    assert "/api/edit/selection_set_gaps" in app
    assert "def export_selection_set_preview" in mcp
    assert "def selection_set_gaps" in mcp
    assert 'id="btn-exp-preview-set"' in html
    assert 'id="btn-gaps-set"' in html
    assert "exportSelectionSetPreviewUi" in ts
    assert "selectionSetGapsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_preview" in cat["tool_ids"]
    assert "selection_set_gaps" in cat["tool_ids"]
