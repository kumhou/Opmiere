"""markers in/clear selection span + export_selection_otio_json (0.6.42)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_markers_and_otio_selection():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mot_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 10, 0, 20)  # 10..30
        c2 = ed.add_clip(tr.id, med.id, 30, 0, 10)  # 30..40

        ed.project.add_marker(frame=5, label="before")
        ed.project.add_marker(frame=15, label="in")
        ed.project.add_marker(frame=35, label="in2")
        ed.project.add_marker(frame=50, label="after")

        hit = ed.markers_in_selection_span([c1.id, c2.id])
        assert hit["count"] == 2
        labels = {m["label"] for m in hit["markers"]}
        assert labels == {"in", "in2"}

        clr = ed.clear_markers_in_selection_span([c1.id, c2.id])
        assert clr["count"] == 2
        remain = {m.label for m in ed.project.markers}
        assert "before" in remain
        assert "after" in remain
        assert "in" not in remain

        out = root / "sel.otio.json"
        ot = ed.export_selection_otio_json([c1.id], path=out)
        assert ot["clip_count"] == 1
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["tracks"]
        assert data["metadata"]["opmiere"]["selection_clip_ids"] == [c1.id]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_42():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/markers_in_selection_span" in app
    assert "/api/edit/clear_markers_in_selection_span" in app
    assert "/api/edit/export_selection_otio" in app
    assert "def markers_in_selection_span" in mcp
    assert "def clear_markers_in_selection_span" in mcp
    assert "def export_selection_otio_json" in mcp
    assert 'id="btn-mkr-in-sel"' in html
    assert 'id="btn-clr-mkr-sel"' in html
    assert 'id="btn-otio-sel"' in html
    assert "markersInSelectionSpanUi" in ts
    assert "clearMarkersInSelectionSpanUi" in ts
    assert "exportSelectionOtioUi" in ts
