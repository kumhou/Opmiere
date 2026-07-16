"""export_track_only + export_selection_mp4 + export_work_area_mp4 (0.6.4)."""

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


def test_export_track_selection_work_area():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ex_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        tr2 = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.place_from_file(v, "video", tr2.id, 0)
        # mute state should restore after track-only export
        ed.set_track_muted(tr2.id, False)
        out = ed.export_track_only(tr.id, root / "t.mp4", clip_id=c.id)
        assert Path(out["path"]).exists()
        assert out["track_id"] == tr.id
        assert ed.project.track_by_id(tr2.id).muted is False

        sel = ed.export_selection_mp4([c.id], root / "s.mp4")
        assert Path(sel["path"]).exists()
        assert sel["start_frame"] == c.start

        ed.set_in_point(0)
        ed.set_out_point(8)
        wa = ed.export_work_area_mp4(root / "w.mp4")
        assert Path(wa["path"]).exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_4():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/track_only" in app
    assert "/api/export/selection_mp4" in app
    assert "/api/export/work_area_mp4" in app
    assert "def export_track_only" in mcp
    assert "def export_selection_mp4" in mcp
    assert "def export_work_area_mp4" in mcp
    assert 'id="btn-trk-only"' in html
    assert 'id="btn-sel-mp4"' in html
    assert 'id="btn-wa-mp4"' in html
    assert "exportTrackOnlyUi" in ts
    assert "exportSelectionMp4Ui" in ts
    assert "exportWorkAreaMp4Ui" in ts
