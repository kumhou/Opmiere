"""export_selection_edl/cutlist/fcpxml defaults (0.6.43)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_edl_cutlist_fcpxml_defaults():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ecf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 12)
        c2 = ed.add_clip(tr.id, med.id, 12, 0, 12)

        edl = ed.export_selection_edl_default([c1.id, c2.id], filename="s.edl")
        assert edl["count"] == 2
        ep = Path(edl["path"] or "")
        assert ep.is_file()
        assert "TITLE:" in ep.read_text(encoding="utf-8")

        cl = ed.export_selection_cutlist_default(
            [c1.id, c2.id], filename="s.csv", format="csv",
        )
        assert cl["count"] == 2
        assert Path(cl["path"] or "").is_file()

        fcp = ed.export_selection_fcpxml_default(
            [c1.id, c2.id], filename="s.fcpxml", title="TestSel",
        )
        assert fcp["count"] == 2
        fp = Path(fcp["path"] or "")
        assert fp.is_file()
        text = fp.read_text(encoding="utf-8")
        assert "fcpxml" in text
        assert "asset-clip" in text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_43():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_edl_default" in app
    assert "/api/edit/export_selection_cutlist_default" in app
    assert "/api/edit/export_selection_fcpxml" in app
    assert "def export_selection_edl_default" in mcp
    assert "def export_selection_cutlist_default" in mcp
    assert "def export_selection_fcpxml" in mcp
    assert 'id="btn-edl-def-sel"' in html
    assert 'id="btn-cutlist-def-sel"' in html
    assert 'id="btn-fcpxml-sel"' in html
    assert "exportSelectionEdlDefaultUi" in ts
    assert "exportSelectionCutlistDefaultUi" in ts
    assert "exportSelectionFcpxmlUi" in ts
