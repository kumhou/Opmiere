"""clear_selection_set_safe_areas + clear_selection_set_timecodes (0.9.63)."""

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


def test_clear_safe_and_timecode_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_clrstc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])
        ed.safe_area_selection_set("hero")
        ed.timecode_selection_set("hero")

        sa = ed.clear_selection_set_safe_areas("hero")
        assert sa.get("selection_set") == "hero"
        assert int(sa.get("count") or 0) >= 1

        tc = ed.clear_selection_set_timecodes("hero")
        assert tc.get("selection_set") == "hero"
        assert int(tc.get("count") or 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_63():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/clear_selection_set_safe_areas" in app
    assert "/api/edit/clear_selection_set_timecodes" in app
    assert "def clear_selection_set_safe_areas" in mcp
    assert "def clear_selection_set_timecodes" in mcp
    assert 'id="btn-clr-safe-set"' in html
    assert 'id="btn-clr-tc-set"' in html
    assert "clearSelectionSetSafeAreasUi" in ts
    assert "clearSelectionSetTimecodesUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "clear_selection_set_safe_areas" in cat["tool_ids"]
    assert "clear_selection_set_timecodes" in cat["tool_ids"]
