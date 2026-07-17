"""selection_checklist + export_selection_checklist (0.6.90)."""

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
            "-f", "lavfi", "-i", f"sine=f=610:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_checklist_and_export():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cl_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        cl = ed.selection_checklist([c.id])
        assert cl.get("ok") is True
        assert int(cl.get("fail_count") or 0) == 0
        assert len(cl.get("items") or []) >= 5
        assert all("status" in i and "action" in i for i in cl["items"])

        exp = ed.export_selection_checklist([c.id], format="md")
        p = Path(exp.get("path") or "")
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        assert "Selection checklist" in text
        assert "Status" in text

        expj = ed.export_selection_checklist(
            [c.id], filename="selection_checklist.json", format="json",
        )
        assert Path(expj["path"]).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_90():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_checklist" in app
    assert "/api/edit/export_selection_checklist" in app
    assert "def selection_checklist" in mcp
    assert "def export_selection_checklist" in mcp
    assert 'id="btn-check-sel"' in html
    assert 'id="btn-check-exp-sel"' in html
    assert "selectionChecklistUi" in ts
    assert "exportSelectionChecklistUi" in ts
