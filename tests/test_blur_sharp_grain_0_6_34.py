"""blur_selection + sharpen_selection + film_grain_selection (0.6.34)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=gray:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _has_fx(clip, etype: str) -> bool:
    return any(
        isinstance(e, dict) and e.get("type") == etype
        for e in (clip.effects or [])
    )


def test_blur_sharp_grain():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bsg_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 12)
        c2 = ed.add_clip(tr.id, med.id, 12, 0, 12)

        bl = ed.blur_selection([c1.id], amount=3.0)
        assert bl["count"] == 1
        assert _has_fx(ed._find_clip(c1.id), "blur")

        sh = ed.sharpen_selection([c1.id, c2.id], amount=1.2)
        assert sh["count"] == 2
        assert _has_fx(ed._find_clip(c2.id), "sharpen")

        gr = ed.film_grain_selection([c2.id], amount=15.0)
        assert gr["count"] == 1
        assert _has_fx(ed._find_clip(c2.id), "film_grain")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_34():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/blur_selection" in app
    assert "/api/edit/sharpen_selection" in app
    assert "/api/edit/film_grain_selection" in app
    assert "def blur_selection" in mcp
    assert "def sharpen_selection" in mcp
    assert "def film_grain_selection" in mcp
    assert 'id="btn-blur-sel"' in html
    assert 'id="btn-sharp-sel"' in html
    assert 'id="btn-grain-sel"' in html
    assert "blurSelectionUi" in ts
    assert "sharpenSelectionUi" in ts
    assert "filmGrainSelectionUi" in ts
