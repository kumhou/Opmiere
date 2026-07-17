"""markers_in_selection_set_span + clear_markers_in_selection_set_span (0.9.74)."""

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
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_markers_in_and_clear_span_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_spanmkr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])
        ed.add_marker(frame=3, label="inside")
        ed.add_marker(frame=100, label="outside")

        listed = ed.markers_in_selection_set_span("hero")
        assert listed.get("selection_set") == "hero"
        assert int(listed.get("count") or 0) >= 1
        labels = {m.get("label") for m in (listed.get("markers") or [])}
        assert "inside" in labels
        assert "outside" not in labels

        cleared = ed.clear_markers_in_selection_set_span("hero")
        assert cleared.get("selection_set") == "hero"
        assert int(cleared.get("count") or 0) >= 1
        after = ed.markers_in_selection_set_span("hero")
        assert int(after.get("count") or 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_74():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/markers_in_selection_set_span" in app
    assert "/api/edit/clear_markers_in_selection_set_span" in app
    assert "def markers_in_selection_set_span" in mcp
    assert "def clear_markers_in_selection_set_span" in mcp
    assert 'id="btn-span-mkr-set"' in html
    assert 'id="btn-clr-span-mkr-set"' in html
    assert "markersInSelectionSetSpanUi" in ts
    assert "clearMarkersInSelectionSetSpanUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "markers_in_selection_set_span" in cat["tool_ids"]
    assert "clear_markers_in_selection_set_span" in cat["tool_ids"]
