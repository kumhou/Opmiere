"""export_selection_gif/webm + trim_selection_to_playhead (0.6.10)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_selection_export_and_trim():
    root = Path(tempfile.mkdtemp(prefix="opmiere_set_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        g = ed.export_selection_gif([c.id], root / "s.gif", fps=8, width=100)
        assert Path(g["path"]).exists()
        assert g["bytes"] > 0
        w = ed.export_selection_webm([c.id], root / "s.webm", crf=40, width=120)
        assert Path(w["path"]).exists()
        assert w["bytes"] > 0

        mid = c.start + c.timeline_duration_frames // 2
        old_end = c.end
        trm = ed.trim_selection_to_playhead([c.id], mid, edge="tail", mode="normal")
        assert trm["count"] == 1
        assert ed._find_clip(c.id).end == mid
        assert ed._find_clip(c.id).end < old_end

        # re-place for work area export
        c2 = ed.place_from_file(v, "video", tr.id, int(ed._find_clip(c.id).end))
        wa = ed.set_work_area_from_selection_export([c.id, c2.id], root / "wa.mp4")
        assert Path(wa["path"]).exists()
        io = ed.get_in_out()
        assert io.get("ready") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_10():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/selection_gif" in app
    assert "/api/export/selection_webm" in app
    assert "/api/edit/trim_selection_playhead" in app
    assert "/api/export/work_area_from_selection" in app
    assert "def export_selection_gif" in mcp
    assert "def export_selection_webm" in mcp
    assert "def trim_selection_to_playhead" in mcp
    assert "def set_work_area_from_selection_export" in mcp
    assert 'id="btn-sel-gif"' in html
    assert 'id="btn-sel-webm"' in html
    assert 'id="btn-trim-q"' in html
    assert 'id="btn-trim-w"' in html
    assert 'id="btn-wa-sel"' in html
    assert "exportSelectionGifUi" in ts
    assert "exportSelectionWebmUi" in ts
    assert "trimSelectionPlayheadUi" in ts
    assert "workAreaFromSelectionExportUi" in ts
