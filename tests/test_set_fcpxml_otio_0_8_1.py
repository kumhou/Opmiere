"""export_selection_set_fcpxml + export_selection_set_otio (0.8.1)."""

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
            "-f", "lavfi", "-i", f"color=c=lime:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=120:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_set_fcpxml_and_otio():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fo_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        ed.save_selection_set("hero", [c.id])

        fcp = ed.export_selection_set_fcpxml("hero")
        assert fcp.get("ok") is True
        fpath = Path(fcp.get("path") or "")
        assert fpath.is_file()
        ftext = fpath.read_text(encoding="utf-8", errors="replace")
        assert "fcpxml" in ftext.lower() or "<?xml" in ftext

        otio = ed.export_selection_set_otio("hero")
        assert otio.get("ok") is True
        opath = Path(otio.get("path") or "")
        assert opath.is_file()
        otext = opath.read_text(encoding="utf-8", errors="replace")
        assert "clip" in otext.lower() or "track" in otext.lower() or "{" in otext
        assert otio.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_1():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_fcpxml" in app
    assert "/api/edit/export_selection_set_otio" in app
    assert "def export_selection_set_fcpxml" in mcp
    assert "def export_selection_set_otio" in mcp
    assert 'id="btn-set-fcpxml"' in html
    assert 'id="btn-set-otio"' in html
    assert "exportSelectionSetFcpxmlUi" in ts
    assert "exportSelectionSetOtioUi" in ts
