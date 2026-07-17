"""clear_selection_set_fades + clear_selection_set_position (0.9.20)."""

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


def test_clear_fades_and_position_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cfp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        ed.set_selection_set_fades("hero", fade_in_frames=3, fade_out_frames=3)
        assert ed.selection_set_fades_report("hero").get("with_fades", 0) >= 1
        clr_f = ed.clear_selection_set_fades("hero")
        assert clr_f.get("selection_set") == "hero"
        assert ed.selection_set_fades_report("hero").get("with_fades", 0) == 0

        ed.set_selection_set_position("hero", 0.1, 0.1, 0.4)
        assert ed.selection_set_position_report("hero").get("with_position", 0) >= 1
        clr_p = ed.clear_selection_set_position("hero")
        assert clr_p.get("selection_set") == "hero"
        assert ed.selection_set_position_report("hero").get("with_position", 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_20():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/clear_selection_set_fades" in app
    assert "/api/edit/clear_selection_set_position" in app
    assert "def clear_selection_set_fades" in mcp
    assert "def clear_selection_set_position" in mcp
    assert 'id="btn-clr-fade-set"' in html
    assert 'id="btn-clr-pos-set"' in html
    assert "clearSelectionSetFadesUi" in ts
    assert "clearSelectionSetPositionUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "clear_selection_set_fades" in cat["tool_ids"]
    assert "clear_selection_set_position" in cat["tool_ids"]
