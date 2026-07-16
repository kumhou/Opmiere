"""add_intro_card + place_quad_screen (0.5.92)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_intro_card_ripple_and_quad():
    root = Path(tempfile.mkdtemp(prefix="opmiere_iq_"))
    try:
        paths = []
        for i, c in enumerate(("navy", "orange", "green", "purple")):
            p = root / f"m{i}.mp4"
            _vid(p, 0.4, c)
            paths.append(p)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        first = ed.place_from_file(paths[0], "video", tr.id, 0)
        assert first.id
        old_start = first.start
        intro = ed.add_intro_card("Hello", duration_frames=30, fade_out_frames=6)
        assert intro["clip_id"]
        card = ed._find_clip(intro["clip_id"])
        assert card.start == 0
        # original content shifted right
        moved = ed._find_clip(first.id)
        assert moved.start >= old_start + 30

        mids = [ed.import_media(p, "video").id for p in paths]
        q = ed.place_quad_screen(mids, start=0, duration_frames=12)
        assert q["count"] == 4
        assert len(q["clips"]) == 4
        slots = {c["slot"] for c in q["clips"]}
        assert slots == {"TL", "TR", "BL", "BR"}
        for item in q["clips"]:
            clip = ed._find_clip(item["clip_id"])
            assert clip.position is not None
            assert abs(float(clip.position["scale"]) - 0.5) < 1e-6
        assert sum(1 for t in ed.project.tracks if t.kind == "video") >= 4
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_92():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/intro_card" in app
    assert "/api/edit/quad_screen" in app
    assert "def add_intro_card" in mcp
    assert "def place_quad_screen" in mcp
    assert 'id="btn-intro"' in html
    assert 'id="btn-quad"' in html
    assert "introCardUi" in ts
    assert "quadScreenUi" in ts
