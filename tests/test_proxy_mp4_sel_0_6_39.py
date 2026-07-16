"""selection_proxy_report + ensure_selection_media_proxies + mp4 default (0.6.39)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_proxy_report_and_mp4():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pmp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        # ensure contiguous for export
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end), duration_frames=5)

        rep = ed.selection_proxy_report([c1.id, c2.id])
        assert rep["count"] >= 1
        assert "proxy_ready_count" in rep

        px = ed.ensure_selection_media_proxies([c1.id], height=90)
        assert px["count"] >= 1 or px["error_count"] == 0
        rep2 = ed.selection_proxy_report([c1.id])
        # after build, ready should be true for video media when encode ok
        if px["count"] >= 1:
            assert rep2["proxy_ready_count"] >= 1

        out = ed.export_selection_mp4_default([c1.id, c2.id], filename="sel.mp4")
        p = Path(out.get("path") or out.get("output_path") or "")
        assert p.is_file() or (ed.bundle.root / "exports" / "sel.mp4").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_39():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_proxy_report" in app
    assert "/api/edit/ensure_selection_media_proxies" in app
    assert "/api/edit/export_selection_mp4_default" in app
    assert "def selection_proxy_report" in mcp
    assert "def ensure_selection_media_proxies" in mcp
    assert "def export_selection_mp4_default" in mcp
    assert 'id="btn-proxy-sel"' in html
    assert 'id="btn-mk-proxy-sel"' in html
    assert 'id="btn-mp4-sel"' in html
    assert "selectionProxyReportUi" in ts
    assert "ensureSelectionMediaProxiesUi" in ts
    assert "exportSelectionMp4DefaultUi" in ts
