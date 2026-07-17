"""selection_set_to_markers + export_selection_set_edl (0.7.9)."""

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
            "-f", "lavfi", "-i", f"color=c=orange:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=140:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_set_to_markers_and_edl():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sme_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, 8, duration_frames=8)
        ed.save_selection_set("hero", [c1.id, c2.id])

        mk = ed.selection_set_to_markers("hero", at="start")
        assert mk.get("ok") is True
        assert mk.get("marker_count") == 2
        assert ed.list_markers()["count"] >= 2

        both = ed.selection_set_to_markers("hero", at="both", label_prefix="H")
        assert both.get("marker_count") == 4

        edl = ed.export_selection_set_edl("hero")
        assert edl.get("ok") is True
        path = Path(edl.get("path") or edl.get("output_path") or "")
        assert path.is_file()
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "TITLE:" in text
        assert edl.get("clip_count") == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_9():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_to_markers" in app
    assert "/api/edit/export_selection_set_edl" in app
    assert "def selection_set_to_markers" in mcp
    assert "def export_selection_set_edl" in mcp
    assert 'id="btn-set-markers"' in html
    assert 'id="btn-set-edl"' in html
    assert "selectionSetToMarkersUi" in ts
    assert "exportSelectionSetEdlUi" in ts
