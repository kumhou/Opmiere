"""extract_selection_set + rate_stretch_selection_set (0.9.23)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_rate_stretch_and_extract_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ess_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        keep = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        doomed = ed.place_from_file(v, "video", tr.id, 12, duration_frames=12)
        ed.save_selection_set("keep", [keep.id])
        ed.save_selection_set("doomed", [doomed.id])

        stretch = ed.rate_stretch_selection_set("keep", 24)
        assert stretch.get("selection_set") == "keep"
        assert stretch.get("count", 0) >= 1
        assert stretch.get("target_duration_frames") == 24

        extracted = ed.extract_selection_set("doomed")
        assert extracted.get("selection_set") == "doomed"
        # set still named but live clips gone
        try:
            ed.selection_set_duration_report("doomed")
            live = True
        except ValueError:
            live = False
        assert live is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_23():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/extract_selection_set" in app
    assert "/api/edit/rate_stretch_selection_set" in app
    assert "def extract_selection_set" in mcp
    assert "def rate_stretch_selection_set" in mcp
    assert 'id="btn-extract-set"' in html
    assert 'id="btn-stretch-set"' in html
    assert "extractSelectionSetUi" in ts
    assert "rateStretchSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "extract_selection_set" in cat["tool_ids"]
    assert "rate_stretch_selection_set" in cat["tool_ids"]
