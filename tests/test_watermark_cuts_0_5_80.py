"""watermark effect + list_cuts + path-C v22 (0.5.80)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.model import KNOWN_EFFECT_TYPES
from opmiere.render.openshot_map import ADAPTER_VERSION, path_c_effect_catalog


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_watermark_and_list_cuts():
    assert "watermark" in KNOWN_EFFECT_TYPES
    assert int(ADAPTER_VERSION) >= 22
    cat = path_c_effect_catalog()
    assert "watermark" in cat["mapped"]
    assert int(cat.get("adapter_version") or 0) >= 22

    root = Path(tempfile.mkdtemp(prefix="opmiere_wm_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        r = ed.set_clip_watermark(c1.id, "© Test", alpha=0.5)
        assert r["enabled"] is True
        assert any(e.get("type") == "watermark" for e in (c1.effects or []))
        cuts = ed.list_cuts(tr.id)
        assert cuts["count"] >= 3  # start, start, end
        assert cuts["hard_cut_count"] >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_80():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/watermark" in app
    assert "/api/edit/cuts" in app
    assert "def set_clip_watermark" in mcp
    assert "def list_cuts" in mcp
    assert 'id="btn-wm"' in html
    assert "watermarkSelectionUi" in ts
