"""clear_selection_set_shape_masks + rename_selection_set_tracks (0.9.62)."""

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


def test_clear_masks_and_rename_tracks_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_clrmask_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])
        ed.shape_mask_selection_set("hero", shape="circle", size=0.5)

        clr = ed.clear_selection_set_shape_masks("hero")
        assert clr.get("selection_set") == "hero"
        assert int(clr.get("count") or 0) >= 1

        ren = ed.rename_selection_set_tracks("hero", prefix="Hero ")
        assert ren.get("selection_set") == "hero"
        assert int(ren.get("count") or 0) >= 1
        assert any(
            str(r.get("to") or "").startswith("Hero ")
            for r in (ren.get("renamed") or [])
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_62():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/clear_selection_set_shape_masks" in app
    assert "/api/edit/rename_selection_set_tracks" in app
    assert "def clear_selection_set_shape_masks" in mcp
    assert "def rename_selection_set_tracks" in mcp
    assert 'id="btn-clr-mask-set"' in html
    assert 'id="btn-ren-trk-set"' in html
    assert "clearSelectionSetShapeMasksUi" in ts
    assert "renameSelectionSetTracksUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "clear_selection_set_shape_masks" in cat["tool_ids"]
    assert "rename_selection_set_tracks" in cat["tool_ids"]
