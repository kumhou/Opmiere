"""luma_key_selection_set + shape_mask_selection_set (0.9.54)."""

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


def test_luma_key_and_shape_mask_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lumask_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        lk = ed.luma_key_selection_set(
            "hero", threshold=0.1, tolerance=0.1, replace=True,
        )
        assert lk.get("selection_set") == "hero"
        assert lk.get("threshold") == 0.1
        assert "count" in lk

        sm = ed.shape_mask_selection_set(
            "hero", shape="circle", size=0.5, replace=True,
        )
        assert sm.get("selection_set") == "hero"
        assert sm.get("shape") == "circle"
        assert "count" in sm
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_54():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/luma_key_selection_set" in app
    assert "/api/edit/shape_mask_selection_set" in app
    assert "def luma_key_selection_set" in mcp
    assert "def shape_mask_selection_set" in mcp
    assert 'id="btn-luma-set"' in html
    assert 'id="btn-mask-set"' in html
    assert "lumaKeySelectionSetUi" in ts
    assert "shapeMaskSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "luma_key_selection_set" in cat["tool_ids"]
    assert "shape_mask_selection_set" in cat["tool_ids"]
