"""apply_film_grain + apply_blur + export_webm (0.5.96)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_grain_blur_webm():
    root = Path(tempfile.mkdtemp(prefix="opmiere_gbw_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        g = ed.apply_film_grain(c.id, amount=15)
        assert g["clip_id"] == c.id
        assert any(
            e.get("type") == "film_grain" and float(e.get("amount", 0)) == 15
            for e in (ed._find_clip(c.id).effects or [])
        )
        b = ed.apply_blur(c.id, amount=3)
        assert b["clip_id"] == c.id
        assert any(e.get("type") == "blur" for e in (ed._find_clip(c.id).effects or []))

        # clear heavy FX for fast export
        with ed._mutate():
            ed._find_clip(c.id).effects = []
        out = ed.export_webm(root / "o.webm", crf=40, width=120)
        assert Path(out["path"]).exists()
        assert out["path"].endswith(".webm")
        assert out["bytes"] > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_96():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/film_grain" in app
    assert "/api/clip/blur" in app
    assert "/api/export/webm" in app
    assert "def apply_film_grain" in mcp
    assert "def apply_blur" in mcp
    assert "def export_webm" in mcp
    assert 'id="btn-grain"' in html
    assert 'id="btn-blur"' in html
    assert 'id="btn-webm"' in html
    assert "filmGrainUi" in ts
    assert "blurUi" in ts
    assert "exportWebmUi" in ts
