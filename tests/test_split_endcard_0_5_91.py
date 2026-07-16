"""place_split_screen + add_end_card (0.5.91)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_split_screen_and_end_card():
    root = Path(tempfile.mkdtemp(prefix="opmiere_split_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.5, "navy")
        _vid(b, 0.4, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        ed.add_track("video")
        m1 = ed.import_media(a, "video")
        m2 = ed.import_media(b, "video")
        sp = ed.place_split_screen(m1.id, m2.id, start=0, orientation="lr")
        assert sp["left_clip_id"]
        assert sp["right_clip_id"]
        assert sp["orientation"] == "lr"
        left = ed._find_clip(sp["left_clip_id"])
        right = ed._find_clip(sp["right_clip_id"])
        assert any(e.get("type") == "crop" for e in (left.effects or []))
        assert right.position is not None
        assert abs(float(right.position["scale"]) - 0.5) < 1e-6
        assert sum(1 for t in ed.project.tracks if t.kind == "video") >= 2

        end = ed.add_end_card("Thanks!", duration_frames=30, fade_in_frames=6)
        assert end["clip_id"]
        card = ed._find_clip(end["clip_id"])
        assert card.start >= sp["duration_frames"] - 1
        assert any(
            e.get("type") == "text" and "Thanks" in str(e.get("content"))
            for e in (card.effects or [])
        )

        tb = ed.place_split_screen(
            m1.id, m2.id, start=int(ed.duration_frames()), orientation="tb",
            duration_frames=10,
        )
        assert tb["orientation"] == "tb"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_91():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/end_card" in app
    assert "/api/edit/split_screen" in app
    assert "def add_end_card" in mcp
    assert "def place_split_screen" in mcp
    assert 'id="btn-endcard"' in html
    assert 'id="btn-split"' in html
    assert "endCardUi" in ts
    assert "splitScreenUi" in ts
