"""flip_selection_set + quantize_selection_set (0.9.89)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_flip_and_quantize_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_flq_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 3, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        flip = ed.flip_selection_set("hero", horizontal=True)
        assert flip.get("selection_set") == "hero"
        assert flip.get("clip_count") == 1

        q = ed.quantize_selection_set("hero", 5, edge="start")
        assert q.get("selection_set") == "hero"
        clip = ed._find_clip(c.id)
        assert int(clip.start) % 5 == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_89():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/flip_selection_set" in app
    assert "/api/edit/quantize_selection_set" in app
    assert "def flip_selection_set" in mcp
    assert "def quantize_selection_set" in mcp
    assert 'id="btn-flip-set"' in html
    assert 'id="btn-quantize-set"' in html
    assert "flipSelectionSetUi" in ts
    assert "quantizeSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "flip_selection_set" in cat["tool_ids"]
    assert "quantize_selection_set" in cat["tool_ids"]
