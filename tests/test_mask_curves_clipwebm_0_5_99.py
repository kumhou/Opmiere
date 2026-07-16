"""apply_shape_mask + apply_curves + export_clip_webm (0.5.99)."""

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


def test_mask_curves_clip_webm():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mcw_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        m = ed.apply_shape_mask(c.id, shape="circle", size=0.6)
        assert m["clip_id"] == c.id
        assert any(
            e.get("type") == "shape_mask" and e.get("shape") == "circle"
            for e in (ed._find_clip(c.id).effects or [])
        )
        cr = ed.apply_curves(c.id, preset="vintage")
        assert cr["clip_id"] == c.id
        assert any(
            e.get("type") == "curves" and e.get("preset") == "vintage"
            for e in (ed._find_clip(c.id).effects or [])
        )
        with ed._mutate():
            ed._find_clip(c.id).effects = []
        out = ed.export_clip_webm(c.id, root / "c.webm", crf=40, width=100)
        assert Path(out["path"]).exists()
        assert out["clip_id"] == c.id
        assert out["bytes"] > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_99():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/shape_mask" in app
    assert "/api/clip/curves" in app
    assert "/api/export/clip_webm" in app
    assert "def apply_shape_mask" in mcp
    assert "def apply_curves" in mcp
    assert "def export_clip_webm" in mcp
    assert 'id="btn-mask"' in html
    assert 'id="btn-curves"' in html
    assert 'id="btn-clip-webm"' in html
    assert "shapeMaskUi" in ts
    assert "curvesUi" in ts
    assert "exportClipWebmUi" in ts
