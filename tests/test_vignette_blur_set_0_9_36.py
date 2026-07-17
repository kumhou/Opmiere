"""vignette_selection_set + blur_selection_set (0.9.36)."""

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


def test_vignette_and_blur_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_vb_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        vig = ed.vignette_selection_set("hero", strength=0.35)
        assert vig.get("selection_set") == "hero"
        assert vig.get("strength") == 0.35
        assert vig.get("count", 0) >= 1 or vig.get("error_count", 0) == 0

        blur = ed.blur_selection_set("hero", amount=3.0)
        assert blur.get("selection_set") == "hero"
        assert blur.get("amount") == 3.0
        fx = ed.selection_set_effects_report("hero")
        assert fx.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_36():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/vignette_selection_set" in app
    assert "/api/edit/blur_selection_set" in app
    assert "def vignette_selection_set" in mcp
    assert "def blur_selection_set" in mcp
    assert 'id="btn-vignette-set"' in html
    assert 'id="btn-blur-set"' in html
    assert "vignetteSelectionSetUi" in ts
    assert "blurSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "vignette_selection_set" in cat["tool_ids"]
    assert "blur_selection_set" in cat["tool_ids"]
