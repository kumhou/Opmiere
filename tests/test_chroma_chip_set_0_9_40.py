"""chroma_key_selection_set + color_selection_set (0.9.40)."""

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


def test_chroma_and_color_chip_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        key = ed.chroma_key_selection_set("hero", color="green")
        assert key.get("selection_set") == "hero"
        assert key.get("color") == "green"

        chip = ed.color_selection_set("hero", "red")
        assert chip.get("selection_set") == "hero"
        meta = ed.selection_set_meta_report("hero")
        assert meta.get("colored_count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_40():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/chroma_key_selection_set" in app
    assert "/api/edit/color_selection_set" in app
    assert "def chroma_key_selection_set" in mcp
    assert "def color_selection_set" in mcp
    assert 'id="btn-chroma-set"' in html
    assert 'id="btn-chip-set"' in html
    assert "chromaKeySelectionSetUi" in ts
    assert "colorSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "chroma_key_selection_set" in cat["tool_ids"]
    assert "color_selection_set" in cat["tool_ids"]
