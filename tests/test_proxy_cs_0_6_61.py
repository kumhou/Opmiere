"""ensure_selection_proxies + export_selection_contact_sheet_default (0.6.61)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_proxies_and_contact_sheet():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        px = ed.ensure_selection_proxies([c.id], height=90, force=False)
        assert int(px.get("media_count") or 0) >= 1
        assert int(px.get("ensured_count") or 0) >= 1 or int(px.get("error_count") or 0) == 0
        # second call should cache-hit
        px2 = ed.ensure_selection_proxies([c.id], height=90, force=False)
        assert int(px2.get("ensured_count") or 0) >= 1

        cs = ed.export_selection_contact_sheet_default(
            [c.id], filename="cs.jpg", tile_width=80, tile_height=45,
        )
        p = Path(cs.get("path") or "")
        assert p.is_file()
        assert int(cs.get("tile_count") or 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_61():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/ensure_selection_proxies" in app
    assert "/api/edit/export_selection_contact_sheet_default" in app
    assert "def ensure_selection_proxies" in mcp
    assert "def export_selection_contact_sheet_default" in mcp
    assert 'id="btn-proxy-sel"' in html
    assert 'id="btn-cs-def-sel"' in html
    assert "ensureSelectionProxiesUi" in ts
    assert "exportSelectionContactSheetDefaultUi" in ts
