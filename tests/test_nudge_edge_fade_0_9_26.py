"""nudge_selection_set + apply_edge_fades_to_selection_set (0.9.26)."""

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


def test_nudge_and_edge_fades_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_nef_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        nudged = ed.nudge_selection_set("hero", 6)
        assert nudged.get("selection_set") == "hero"
        assert nudged.get("delta_frames") == 6
        clip = ed._find_clip(c.id)
        assert int(clip.start) == 6

        fades = ed.apply_edge_fades_to_selection_set(
            "hero", fade_in_frames=3, fade_out_frames=3,
        )
        assert fades.get("selection_set") == "hero"
        fr = ed.selection_set_fades_report("hero")
        assert fr.get("with_fades", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_26():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/nudge_selection_set" in app
    assert "/api/edit/apply_edge_fades_to_selection_set" in app
    assert "def nudge_selection_set" in mcp
    assert "def apply_edge_fades_to_selection_set" in mcp
    assert 'id="btn-nudge-set"' in html
    assert 'id="btn-edge-fade-set"' in html
    assert "nudgeSelectionSetUi" in ts
    assert "applyEdgeFadesToSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "nudge_selection_set" in cat["tool_ids"]
    assert "apply_edge_fades_to_selection_set" in cat["tool_ids"]
