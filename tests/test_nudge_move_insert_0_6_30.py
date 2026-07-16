"""nudge_selection + move_selection_to_frame + insert_time_before_selection (0.6.30)."""

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
            "-f", "lavfi", "-i", f"color=c=silver:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_nudge_move_insert_time():
    root = Path(tempfile.mkdtemp(prefix="opmiere_nmi_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 10, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 30, 0, 10)
        c3 = ed.add_clip(tr.id, med.id, 50, 0, 10)

        ng = ed.nudge_selection([c1.id, c2.id], 5)
        assert ng["count"] == 2
        assert ed._find_clip(c1.id).start == 15
        assert ed._find_clip(c2.id).start == 35

        mv = ed.move_selection_to_frame([c1.id, c2.id], 0)
        assert ed._find_clip(c1.id).start == 0
        assert ed._find_clip(c2.id).start == 20
        assert mv.get("count", 0) >= 1 or "moved" in mv

        # c3 at 50; insert 10f before c2 (start 20) → c2 and c3 shift
        ins = ed.insert_time_before_selection([c2.id], 10)
        assert ins["count"] >= 2
        assert ed._find_clip(c2.id).start == 30
        assert ed._find_clip(c3.id).start == 60
        assert ed._find_clip(c1.id).start == 0  # before cut
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_30():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/nudge_selection" in app
    assert "/api/edit/move_selection_to_frame" in app
    assert "/api/edit/insert_time_before_selection" in app
    assert "def nudge_selection" in mcp
    assert "def move_selection_to_frame" in mcp
    assert "def insert_time_before_selection" in mcp
    assert 'id="btn-nudge-sel-m"' in html
    assert 'id="btn-nudge-sel-p"' in html
    assert 'id="btn-move-ph-sel"' in html
    assert 'id="btn-ins-time-sel"' in html
    assert "nudgeSelectionUi" in ts
    assert "moveSelectionToPlayheadUi" in ts
    assert "insertTimeBeforeSelectionUi" in ts
