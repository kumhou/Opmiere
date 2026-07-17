"""link_selection_set + set_selection_set_position (0.9.17)."""

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


def test_link_and_position_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lps_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 12, duration_frames=12)
        ed.save_selection_set("hero", [c1.id, c2.id])

        linked = ed.link_selection_set("hero")
        assert linked.get("selection_set") == "hero"
        assert linked.get("clip_count") == 2
        lr = ed.selection_set_link_report("hero")
        assert lr.get("linked_count", 0) >= 1

        pos = ed.set_selection_set_position("hero", 0.1, 0.2, 0.4)
        assert pos.get("selection_set") == "hero"
        assert pos.get("x") == 0.1
        assert pos.get("scale") == 0.4
        pr = ed.selection_set_position_report("hero")
        assert pr.get("with_position", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_17():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/link_selection_set" in app
    assert "/api/edit/set_selection_set_position" in app
    assert "def link_selection_set" in mcp
    assert "def set_selection_set_position" in mcp
    assert 'id="btn-link-set"' in html
    assert 'id="btn-pos-set"' in html
    assert "linkSelectionSetUi" in ts
    assert "setSelectionSetPositionUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "link_selection_set" in cat["tool_ids"]
    assert "set_selection_set_position" in cat["tool_ids"]
