"""apply_vignette + export_clip_gif (0.5.95)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_vignette_and_clip_gif():
    root = Path(tempfile.mkdtemp(prefix="opmiere_vig_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        r = ed.apply_vignette(c.id, strength=0.5)
        assert r["clip_id"] == c.id
        assert any(
            e.get("type") == "vignette" and float(e.get("strength", 0)) == 0.5
            for e in (ed._find_clip(c.id).effects or [])
        )
        g = ed.export_clip_gif(c.id, root / "c.gif", fps=8, width=100)
        assert Path(g["path"]).exists()
        assert g["clip_id"] == c.id
        assert g["bytes"] > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_95():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/vignette" in app
    assert "/api/export/clip_gif" in app
    assert "def apply_vignette" in mcp
    assert "def export_clip_gif" in mcp
    assert 'id="btn-vig"' in html
    assert 'id="btn-clip-gif"' in html
    assert "vignetteUi" in ts
    assert "exportClipGifUi" in ts
