"""selection_muted_report + selection_track_report (0.6.87)."""

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
            "-f", "lavfi", "-i", f"sine=f=580:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_muted_and_track_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mt_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)

        if hasattr(ed, "set_clips_muted"):
            ed.set_clips_muted([c1.id], True)
        elif hasattr(ed, "mute_selection"):
            ed.mute_selection([c1.id])

        mr = ed.selection_muted_report([c1.id, c2.id])
        assert int(mr.get("count") or 0) == 2
        assert int(mr.get("muted_count") or 0) >= 1

        trr = ed.selection_track_report([c1.id, c2.id])
        assert int(trr.get("track_count") or 0) >= 1
        assert int(trr.get("clip_count") or 0) == 2
        assert trr["tracks"][0]["track_id"] == tr.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_87():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_muted_report" in app
    assert "/api/edit/selection_track_report" in app
    assert "def selection_muted_report" in mcp
    assert "def selection_track_report" in mcp
    assert 'id="btn-mute-rep-sel"' in html
    assert 'id="btn-trk-rep-sel"' in html
    assert "selectionMutedReportUi" in ts
    assert "selectionTrackReportUi" in ts
