"""make_selection_set_contact_sheet + finish_selection_set_review_export (0.9.72)."""

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


def test_contact_sheet_and_finish_review_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cfreview_"))
    try:
        v = root / "v.mp4"
        sheet = root / "sheet.jpg"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        cs = ed.make_selection_set_contact_sheet(
            "hero", output_path=str(sheet), max_tiles=4,
        )
        assert cs.get("selection_set") == "hero"
        assert cs.get("path")
        assert Path(str(cs["path"])).is_file()

        fr = ed.finish_selection_set_review_export(
            "hero",
            filename="hero_client_review.mp4",
            clear_overlays=True,
        )
        assert fr.get("selection_set") == "hero"
        assert fr.get("export_path") or (fr.get("export") or {}).get("path")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_72():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/make_selection_set_contact_sheet" in app
    assert "/api/edit/finish_selection_set_review_export" in app
    assert "def make_selection_set_contact_sheet" in mcp
    assert "def finish_selection_set_review_export" in mcp
    assert 'id="btn-contact-set"' in html
    assert 'id="btn-fin-review-set"' in html
    assert "makeSelectionSetContactSheetUi" in ts
    assert "finishSelectionSetReviewExportUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "make_selection_set_contact_sheet" in cat["tool_ids"]
    assert "finish_selection_set_review_export" in cat["tool_ids"]
