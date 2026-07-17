"""selection_set_span + export_selection_set_otio_json (0.9.88)."""

from __future__ import annotations

import json
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


def test_span_and_otio_json_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_spanot_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        span = ed.selection_set_span("hero")
        assert span.get("selection_set") == "hero"
        assert span.get("start_frame") == 0
        assert span.get("end_frame") == 12
        assert span.get("duration_frames") == 12

        exp = ed.export_selection_set_otio_json("hero")
        assert exp.get("selection_set") == "hero"
        path = exp.get("path")
        assert path and Path(str(path)).is_file()
        data = json.loads(Path(str(path)).read_text(encoding="utf-8"))
        assert data.get("OTIO_SCHEMA") or exp.get("timeline")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_88():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_span" in app
    assert "/api/edit/export_selection_set_otio_json" in app
    assert "def selection_set_span" in mcp
    assert "def export_selection_set_otio_json" in mcp
    assert 'id="btn-span-set"' in html
    assert 'id="btn-exp-otio-json-set"' in html
    assert "selectionSetSpanUi" in ts
    assert "exportSelectionSetOtioJsonUi" in ts
    # no duplicate match_frame method
    ops = (root / "src/opmiere/ops.py").read_text(encoding="utf-8")
    assert ops.count("def match_frame_selection_set") == 1
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_span" in cat["tool_ids"]
    assert "export_selection_set_otio_json" in cat["tool_ids"]
    assert cat["tool_ids"].count("match_frame_selection_set") == 1
