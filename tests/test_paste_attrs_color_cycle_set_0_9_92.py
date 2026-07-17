"""paste_attributes_to_selection_set + set_selection_set_color_cycle (0.9.92)."""

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


def test_paste_attrs_and_color_cycle_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pattr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        src = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        dst = ed.place_from_file(v, "video", tr.id, 12, duration_frames=12)
        with ed._mutate():
            ed._find_clip(src.id).speed = 1.5
        ed.copy_attributes(src.id)
        ed.save_selection_set("targets", [dst.id])

        paste = ed.paste_attributes_to_selection_set("targets", speed=True)
        assert paste.get("selection_set") == "targets"
        assert abs(float(ed._find_clip(dst.id).speed) - 1.5) < 1e-6

        ed.save_selection_set("hero", [src.id, dst.id])
        cycle = ed.set_selection_set_color_cycle("hero")
        assert cycle.get("selection_set") == "hero"
        assert cycle.get("count", 0) >= 2
        colors = {ed._find_clip(src.id).color, ed._find_clip(dst.id).color}
        assert None not in colors
        assert len(colors) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_92():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/paste_attributes_to_selection_set" in app
    assert "/api/edit/set_selection_set_color_cycle" in app
    assert "def paste_attributes_to_selection_set" in mcp
    assert "def set_selection_set_color_cycle" in mcp
    assert 'id="btn-paste-attrs-set"' in html
    assert 'id="btn-color-cycle-set"' in html
    assert "pasteAttributesToSelectionSetUi" in ts
    assert "setSelectionSetColorCycleUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "paste_attributes_to_selection_set" in cat["tool_ids"]
    assert "set_selection_set_color_cycle" in cat["tool_ids"]
