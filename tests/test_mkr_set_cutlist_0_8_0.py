"""markers_to_selection_set + export_selection_set_cutlist (0.8.0)."""

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
            "-f", "lavfi", "-i", f"color=c=pink:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=130:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_markers_to_set_and_cutlist():
    root = Path(tempfile.mkdtemp(prefix="opmiere_m80_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)

        ed.add_marker(frame=2, label="shot/1")
        ed.add_marker(frame=12, label="shot/2")
        built = ed.markers_to_selection_set(
            "from_mkr",
            label_prefix="shot/",
            kind="video",
            overwrite=True,
        )
        assert built.get("ok") is True
        assert set(built["clip_ids"]) == {c1.id, c2.id}
        assert built.get("clip_count") == 2

        cut = ed.export_selection_set_cutlist("from_mkr", format="csv")
        assert cut.get("ok") is True
        path = Path(cut.get("path") or "")
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "clip_id" in text or "event" in text
        assert cut.get("clip_count") == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_0():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/markers_to_selection_set" in app
    assert "/api/edit/export_selection_set_cutlist" in app
    assert "def markers_to_selection_set" in mcp
    assert "def export_selection_set_cutlist" in mcp
    assert 'id="btn-mkr-to-set"' in html
    assert 'id="btn-set-cutlist"' in html
    assert "markersToSelectionSetUi" in ts
    assert "exportSelectionSetCutlistUi" in ts
