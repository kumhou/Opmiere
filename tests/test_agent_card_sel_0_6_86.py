"""selection_agent_card + export_selection_agent_card (0.6.86)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=maroon:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=570:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_agent_card_and_export():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ac_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        card = ed.selection_agent_card([c.id])
        assert card.get("schema") == "opmiere.selection_agent_card.v1"
        assert int(card.get("clip_count") or 0) == 1
        assert "health" in card
        assert "duration" in card
        assert "levels" in card
        assert card.get("ok") is True

        exp = ed.export_selection_agent_card([c.id])
        p = Path(exp.get("path") or "")
        assert p.is_file()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded.get("schema") == "opmiere.selection_agent_card.v1"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_86():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_agent_card" in app
    assert "/api/edit/export_selection_agent_card" in app
    assert "def selection_agent_card" in mcp
    assert "def export_selection_agent_card" in mcp
    assert 'id="btn-agent-card-sel"' in html
    assert 'id="btn-agent-card-exp-sel"' in html
    assert "selectionAgentCardUi" in ts
    assert "exportSelectionAgentCardUi" in ts
