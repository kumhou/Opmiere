"""export_selection_set_storyboard + agent_card (0.9.0)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=sienna:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=140:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_storyboard_and_agent_card():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ssc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id], note="h")

        board = ed.export_selection_set_storyboard(
            "hero",
            include_markers=True,
            include_clip_mids=True,
            include_contact=True,
            width=160,
            max_stills=8,
        )
        assert board.get("ok") is True
        assert board.get("selection_set") == "hero"
        assert Path(board["out_dir"]).is_dir()

        card = ed.export_selection_set_agent_card("hero")
        assert card.get("selection_set") == "hero"
        path = Path(card.get("path") or "")
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "clip_ids" in data or "schema" in data or "clip_count" in data
        assert card.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_0():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_storyboard" in app
    assert "/api/edit/export_selection_set_agent_card" in app
    assert "def export_selection_set_storyboard" in mcp
    assert "def export_selection_set_agent_card" in mcp
    assert 'id="btn-set-story"' in html
    assert 'id="btn-set-card"' in html
    assert "exportSelectionSetStoryboardUi" in ts
    assert "exportSelectionSetAgentCardUi" in ts
