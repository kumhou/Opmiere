"""watermark_selection_set + apply_lut_selection_set (0.9.51)."""

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


def _tiny_cube(path: Path) -> None:
    path.write_text(
        "TITLE \"Identity\"\n"
        "LUT_3D_SIZE 2\n"
        "0 0 0\n1 0 0\n0 1 0\n1 1 0\n"
        "0 0 1\n1 0 1\n0 1 1\n1 1 1\n",
        encoding="utf-8",
    )


def test_watermark_and_lut_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wmlut_"))
    try:
        v = root / "v.mp4"
        cube = root / "id.cube"
        _vid(v, 0.5)
        _tiny_cube(cube)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        wm = ed.watermark_selection_set("hero", "DRAFT", position="bottom")
        assert wm.get("selection_set") == "hero"
        assert wm.get("content") == "DRAFT"
        assert "count" in wm

        lut = ed.apply_lut_selection_set("hero", str(cube), replace=True)
        assert lut.get("selection_set") == "hero"
        assert int(lut.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "lut3d" in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_51():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/watermark_selection_set" in app
    assert "/api/edit/apply_lut_selection_set" in app
    assert "def watermark_selection_set" in mcp
    assert "def apply_lut_selection_set" in mcp
    assert 'id="btn-wm-set"' in html
    assert 'id="btn-lut-set"' in html
    assert "watermarkSelectionSetUi" in ts
    assert "applyLutSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "watermark_selection_set" in cat["tool_ids"]
    assert "apply_lut_selection_set" in cat["tool_ids"]
