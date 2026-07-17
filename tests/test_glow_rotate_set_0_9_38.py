"""glow_selection_set + rotate_selection_set (0.9.38)."""

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


def test_glow_and_rotate_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_gr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        glow = ed.glow_selection_set("hero", amount=6.0, intensity=0.3)
        assert glow.get("selection_set") == "hero"
        assert glow.get("amount") == 6.0

        rot = ed.rotate_selection_set("hero", 15.0)
        assert rot.get("selection_set") == "hero"
        assert rot.get("degrees") == 15.0
        fx = ed.selection_set_effects_report("hero")
        assert fx.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_38():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/glow_selection_set" in app
    assert "/api/edit/rotate_selection_set" in app
    assert "def glow_selection_set" in mcp
    assert "def rotate_selection_set" in mcp
    assert 'id="btn-glow-set"' in html
    assert 'id="btn-rotate-set"' in html
    assert "glowSelectionSetUi" in ts
    assert "rotateSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "glow_selection_set" in cat["tool_ids"]
    assert "rotate_selection_set" in cat["tool_ids"]
