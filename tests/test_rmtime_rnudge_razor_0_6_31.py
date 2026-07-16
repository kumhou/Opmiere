"""remove_time_before_selection + ripple_nudge_selection + razor_selection_at (0.6.31)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=crimson:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_rmtime_rnudge_razor():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rrr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c0 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c1 = ed.add_clip(tr.id, med.id, 20, 0, 20)
        c2 = ed.add_clip(tr.id, med.id, 50, 0, 10)

        ed.insert_time_before_selection([c1.id], 10)
        assert ed._find_clip(c1.id).start == 30
        assert ed._find_clip(c2.id).start == 60

        rm = ed.remove_time_before_selection([c1.id], 10)
        assert rm["count"] >= 2
        assert ed._find_clip(c1.id).start == 20
        assert ed._find_clip(c2.id).start == 50
        assert ed._find_clip(c0.id).start == 0

        rn = ed.ripple_nudge_selection([c1.id], 5)
        assert rn["count"] == 1
        assert ed._find_clip(c1.id).start == 25
        assert ed._find_clip(c2.id).start == 55

        # razor c1 (25..45) at mid 35
        rz = ed.razor_selection_at([c1.id], 35)
        assert rz["count"] == 1
        assert len(ed.project.track_by_id(tr.id).clips) == 4
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_31():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/remove_time_before_selection" in app
    assert "/api/edit/ripple_nudge_selection" in app
    assert "/api/edit/razor_selection_at" in app
    assert "def remove_time_before_selection" in mcp
    assert "def ripple_nudge_selection" in mcp
    assert "def razor_selection_at" in mcp
    assert 'id="btn-rm-time-sel"' in html
    assert 'id="btn-rnudge-sel-m"' in html
    assert 'id="btn-rnudge-sel-p"' in html
    assert 'id="btn-razor-sel-at"' in html
    assert "removeTimeBeforeSelectionUi" in ts
    assert "rippleNudgeSelectionUi" in ts
    assert "razorSelectionAtUi" in ts
