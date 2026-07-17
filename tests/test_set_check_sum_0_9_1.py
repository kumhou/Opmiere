"""export_selection_set_checklist + selection_set_export_summary (0.9.1)."""

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
            "-f", "lavfi", "-i", f"color=c=darkorchid:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=130:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_checklist_and_export_summary():
    root = Path(tempfile.mkdtemp(prefix="opmiere_scs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id], note="h")

        cl = ed.export_selection_set_checklist("hero", format="md")
        assert cl.get("ok") is True
        assert cl.get("selection_set") == "hero"
        path = Path(cl.get("path") or "")
        assert path.is_file()

        summ = ed.selection_set_export_summary("hero")
        assert summ.get("selection_set") == "hero"
        assert summ.get("clip_count") == 1
        assert "tools" in summ
        assert summ["tools"].get("mp4") == "export_selection_set_mp4"
        assert "validate_ok" in summ
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_1():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_checklist" in app
    assert "/api/edit/selection_set_export_summary" in app
    assert "def export_selection_set_checklist" in mcp
    assert "def selection_set_export_summary" in mcp
    assert 'id="btn-set-check"' in html
    assert 'id="btn-set-sum"' in html
    assert "exportSelectionSetChecklistUi" in ts
    assert "selectionSetExportSummaryUi" in ts
