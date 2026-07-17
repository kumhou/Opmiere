"""watermark_selection + clear_selection_watermarks (0.6.70)."""

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
            "-f", "lavfi", "-i", f"color=c=gray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=300:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_watermark_selection_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wm_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        r = ed.watermark_selection([c.id], "REVIEW", position="bottom")
        assert int(r.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "watermark" in types

        clr = ed.clear_selection_watermarks([c.id])
        assert int(clr.get("count") or 0) >= 1
        types2 = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "watermark" not in types2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_70():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/watermark_selection" in app
    assert "/api/edit/clear_selection_watermarks" in app
    assert "def watermark_selection" in mcp
    assert "def clear_selection_watermarks" in mcp
    assert 'id="btn-wm-sel"' in html
    assert 'id="btn-wm-clr-sel"' in html
    assert "watermarkSelectionUi" in ts
    assert "clearSelectionWatermarksUi" in ts
