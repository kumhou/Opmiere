"""apply_sharpen + apply_glow + apply_chroma_key (0.5.97)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.3, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_sharpen_glow_chroma():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sgc_"))
    try:
        v = root / "v.mp4"
        g = root / "g.mp4"
        _vid(v, 0.3, "navy")
        _vid(g, 0.3, "green")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        s = ed.apply_sharpen(c.id, amount=1.5)
        assert s["clip_id"] == c.id
        assert any(
            e.get("type") == "sharpen" and float(e.get("amount", 0)) == 1.5
            for e in (ed._find_clip(c.id).effects or [])
        )
        gl = ed.apply_glow(c.id, amount=6, intensity=0.3)
        assert gl["clip_id"] == c.id
        assert any(e.get("type") == "glow" for e in (ed._find_clip(c.id).effects or []))

        m = ed.import_media(g, "video")
        pip = ed.place_pip(m.id, corner="bottom_right", scale=0.4, start=0)
        ck = ed.apply_chroma_key(pip["clip_id"], color="green", similarity=0.2)
        assert ck["clip_id"] == pip["clip_id"]
        assert any(
            e.get("type") == "chroma_key"
            for e in (ed._find_clip(pip["clip_id"]).effects or [])
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_97():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/sharpen" in app
    assert "/api/clip/glow" in app
    assert "/api/clip/chroma_key" in app
    assert "def apply_sharpen" in mcp
    assert "def apply_glow" in mcp
    assert "def apply_chroma_key" in mcp
    assert 'id="btn-sharp"' in html
    assert 'id="btn-glow"' in html
    assert 'id="btn-ckey"' in html
    assert "sharpenUi" in ts
    assert "glowUi" in ts
    assert "chromaKeyUi" in ts
