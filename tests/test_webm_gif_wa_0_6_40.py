"""export_selection_webm/gif_default + work_area_from_selection (0.6.40)."""

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
            "-f", "lavfi", "-i", f"color=c=pink:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=220:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_webm_gif_work_area():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wgw_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        wa = ed.work_area_from_selection([c.id])
        assert wa.get("ready") is True
        assert int(wa["in_frame"]) == 0
        assert int(wa["out_frame"]) == 10

        webm = ed.export_selection_webm_default([c.id], filename="s.webm", width=160)
        wp = Path(webm.get("path") or webm.get("output_path") or "")
        assert wp.is_file() or (ed.bundle.root / "exports" / "s.webm").is_file()

        gif = ed.export_selection_gif_default(
            [c.id], filename="s.gif", fps=10, width=80, max_duration_seconds=2,
        )
        gp = Path(gif.get("path") or gif.get("output_path") or "")
        assert gp.is_file() or (ed.bundle.root / "exports" / "s.gif").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_40():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_webm_default" in app
    assert "/api/edit/export_selection_gif_default" in app
    assert "/api/edit/work_area_from_selection" in app
    assert "def export_selection_webm_default" in mcp
    assert "def export_selection_gif_default" in mcp
    assert "def work_area_from_selection" in mcp
    assert 'id="btn-webm-sel"' in html
    assert 'id="btn-gif-sel"' in html
    assert 'id="btn-wa-from-sel"' in html
    assert "exportSelectionWebmDefaultUi" in ts
    assert "exportSelectionGifDefaultUi" in ts
    assert "workAreaFromSelectionUi" in ts
