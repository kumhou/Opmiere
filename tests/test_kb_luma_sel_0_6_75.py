"""ken_burns_selection + luma_key_selection; dedupe vignette/grain (0.6.75)."""

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
            "-f", "lavfi", "-i", f"color=c=white:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=460:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_ken_burns_and_luma_key_selection():
    root = Path(tempfile.mkdtemp(prefix="opmiere_kl_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        kb = ed.ken_burns_selection([c.id], zoom_start=1.0, zoom_end=1.2)
        assert int(kb.get("count") or 0) >= 1
        lk = ed.luma_key_selection([c.id], threshold=0.15, tolerance=0.1)
        assert int(lk.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "ken_burns" in types
        assert "luma_key" in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_75():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/ken_burns_selection" in app
    assert "/api/edit/luma_key_selection" in app
    assert app.count("@app.post(\"/api/edit/vignette_selection\")") == 1
    assert app.count("@app.post(\"/api/edit/film_grain_selection\")") == 1
    assert "def ken_burns_selection" in mcp
    assert "def luma_key_selection" in mcp
    assert 'id="btn-kb-sel"' in html
    assert 'id="btn-luma-sel"' in html
    assert "kenBurnsSelectionUi" in ts
    assert "lumaKeySelectionUi" in ts
    # no duplicate method defs on Editor source
    ops = (root / "src/opmiere/ops.py").read_text(encoding="utf-8")
    assert ops.count("\n    def vignette_selection(") == 1
    assert ops.count("\n    def film_grain_selection(") == 1
    assert ops.count("\n    def ken_burns_selection(") == 1
