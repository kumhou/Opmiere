"""export_selection_set_markers_default + export_selection_set_markers_srt (0.9.85)."""

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


def test_markers_default_and_srt_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mkrexp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])
        ed.add_marker(frame=2, label="HitA")
        ed.add_marker(frame=8, label="HitB")

        js = ed.export_selection_set_markers_default("hero", format="json")
        assert js.get("selection_set") == "hero"
        path = js.get("path")
        assert path and Path(str(path)).is_file()
        assert js.get("count", 0) >= 1

        srt = ed.export_selection_set_markers_srt(
            "hero", relative=True, cue_seconds=1.0,
        )
        assert srt.get("selection_set") == "hero"
        sp = srt.get("path")
        assert sp and Path(str(sp)).is_file()
        assert srt.get("count", 0) >= 1
        text = Path(str(sp)).read_text(encoding="utf-8")
        assert "HitA" in text or "HitB" in text or "-->" in text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_85():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_markers_default" in app
    assert "/api/edit/export_selection_set_markers_srt" in app
    assert "def export_selection_set_markers_default" in mcp
    assert "def export_selection_set_markers_srt" in mcp
    assert 'id="btn-exp-markers-set"' in html
    assert 'id="btn-exp-markers-srt-set"' in html
    assert "exportSelectionSetMarkersDefaultUi" in ts
    assert "exportSelectionSetMarkersSrtUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_markers_default" in cat["tool_ids"]
    assert "export_selection_set_markers_srt" in cat["tool_ids"]
