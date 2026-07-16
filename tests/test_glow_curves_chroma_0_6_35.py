"""glow_selection + curves_selection + chroma_key_selection (0.6.35)."""

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
            "-f", "lavfi", "-i", f"color=c=green:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _has(clip, etype: str) -> bool:
    return any(
        isinstance(e, dict) and e.get("type") == etype
        for e in (clip.effects or [])
    )


def test_glow_curves_chroma():
    root = Path(tempfile.mkdtemp(prefix="opmiere_gcc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 10, 0, 10)

        gl = ed.glow_selection([c1.id], amount=6.0, intensity=0.3)
        assert gl["count"] == 1
        assert _has(ed._find_clip(c1.id), "glow")

        cu = ed.curves_selection([c1.id, c2.id], preset="increase_contrast")
        assert cu["count"] == 2
        assert _has(ed._find_clip(c2.id), "curves")

        ck = ed.chroma_key_selection([c2.id], color="green")
        assert ck["count"] == 1
        assert _has(ed._find_clip(c2.id), "chroma_key")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_35():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/glow_selection" in app
    assert "/api/edit/curves_selection" in app
    assert "/api/edit/chroma_key_selection" in app
    assert "def glow_selection" in mcp
    assert "def curves_selection" in mcp
    assert "def chroma_key_selection" in mcp
    assert 'id="btn-glow-sel"' in html
    assert 'id="btn-curves-sel"' in html
    assert 'id="btn-chroma-sel"' in html
    assert "glowSelectionUi" in ts
    assert "curvesSelectionUi" in ts
    assert "chromaKeySelectionUi" in ts
