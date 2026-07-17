"""vignette_selection + film_grain_selection (0.6.74)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=450:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_vignette_and_grain_selection():
    root = Path(tempfile.mkdtemp(prefix="opmiere_vg_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        vg = ed.vignette_selection([c.id], strength=0.4)
        assert int(vg.get("count") or 0) >= 1
        gr = ed.film_grain_selection([c.id], amount=10)
        assert int(gr.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "vignette" in types
        assert "film_grain" in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_74():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/vignette_selection" in app
    assert "/api/edit/film_grain_selection" in app
    assert "def vignette_selection" in mcp
    assert "def film_grain_selection" in mcp
    assert 'id="btn-vig-sel"' in html
    assert 'id="btn-grain-sel"' in html
    assert "vignetteSelectionUi" in ts
    assert "filmGrainSelectionUi" in ts
