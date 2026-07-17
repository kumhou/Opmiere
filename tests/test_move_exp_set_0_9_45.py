"""move_selection_set_to_track + expand_selection_set_links (0.9.45)."""

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


def test_move_to_track_and_expand_links():
    root = Path(tempfile.mkdtemp(prefix="opmiere_me_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr1 = ed.add_track("video")
        tr2 = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr1.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        moved = ed.move_selection_set_to_track("hero", tr2.id)
        assert moved.get("selection_set") == "hero"
        assert moved.get("track_id") == tr2.id
        assert moved.get("count", 0) >= 1
        tr, _ = ed._find_clip_and_track(c.id)
        assert tr.id == tr2.id

        exp = ed.expand_selection_set_links("hero", resave=False)
        assert exp.get("selection_set") == "hero"
        assert exp.get("count", 0) >= 1
        assert exp.get("resaved") is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_45():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/move_selection_set_to_track" in app
    assert "/api/edit/expand_selection_set_links" in app
    assert "def move_selection_set_to_track" in mcp
    assert "def expand_selection_set_links" in mcp
    assert 'id="btn-move-trk-set"' in html
    assert 'id="btn-exp-links-set"' in html
    assert "moveSelectionSetToTrackUi" in ts
    assert "expandSelectionSetLinksUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "move_selection_set_to_track" in cat["tool_ids"]
    assert "expand_selection_set_links" in cat["tool_ids"]
