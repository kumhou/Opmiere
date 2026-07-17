"""set_selection_set_opacity + set_selection_set_speed (0.9.16)."""

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


def test_opacity_and_speed_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_oss_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        opac = ed.set_selection_set_opacity("hero", 0.5)
        assert opac.get("selection_set") == "hero"
        assert opac.get("amount") == 0.5

        spd = ed.set_selection_set_speed("hero", 0.5)
        assert spd.get("selection_set") == "hero"
        assert spd.get("speed") == 0.5

        levels = ed.selection_set_levels_report("hero")
        assert levels.get("non_default_count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_16():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/set_selection_set_opacity" in app
    assert "/api/edit/set_selection_set_speed" in app
    assert "def set_selection_set_opacity" in mcp
    assert "def set_selection_set_speed" in mcp
    assert 'id="btn-opac-set"' in html
    assert 'id="btn-speed-set"' in html
    assert "setSelectionSetOpacityUi" in ts
    assert "setSelectionSetSpeedUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "set_selection_set_opacity" in cat["tool_ids"]
    assert "set_selection_set_speed" in cat["tool_ids"]
