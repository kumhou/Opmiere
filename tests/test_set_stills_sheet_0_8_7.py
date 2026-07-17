"""export_selection_set_stills + contact_sheet (0.8.7)."""

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
            "-f", "lavfi", "-i", f"color=c=gold:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=170:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_stills_and_contact_sheet():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sss_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)
        ed.save_selection_set("hero", [c1.id, c2.id])

        stills = ed.export_selection_set_stills(
            "hero", edge="mid", width=160, ext="jpg",
        )
        assert stills.get("ok") is True
        assert stills.get("selection_set") == "hero"
        assert stills.get("clip_count") == 2

        sheet = ed.export_selection_set_contact_sheet(
            "hero",
            max_tiles=8,
            tile_width=80,
            tile_height=45,
        )
        assert sheet.get("ok") is True
        path = Path(sheet.get("export_path") or sheet.get("path") or "")
        assert path.is_file()
        assert path.stat().st_size > 100
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_7():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_stills" in app
    assert "/api/edit/export_selection_set_contact_sheet" in app
    assert "def export_selection_set_stills" in mcp
    assert "def export_selection_set_contact_sheet" in mcp
    assert 'id="btn-set-stills"' in html
    assert 'id="btn-set-sheet"' in html
    assert "exportSelectionSetStillsUi" in ts
    assert "exportSelectionSetContactSheetUi" in ts
