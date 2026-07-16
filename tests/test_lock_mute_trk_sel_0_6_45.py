"""unlock/lock/mute selection tracks (0.6.45)."""

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
            "-f", "lavfi", "-i", f"color=c=brown:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_lock_unlock_mute_tracks():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lmt_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)

        assert ed.project.track_by_id(tr.id).locked is False
        lk = ed.lock_selection_tracks([c1.id])
        assert lk["count"] == 1
        assert ed.project.track_by_id(tr.id).locked is True
        assert ed.selection_locked_tracks([c1.id])["ok"] is False

        un = ed.unlock_selection_tracks([c1.id])
        assert un["count"] == 1
        assert ed.project.track_by_id(tr.id).locked is False

        mu = ed.mute_selection_tracks([c1.id], muted=True)
        assert mu["count"] == 1
        assert ed.project.track_by_id(tr.id).muted is True
        ed.mute_selection_tracks([c1.id], muted=False)
        assert ed.project.track_by_id(tr.id).muted is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_45():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/unlock_selection_tracks" in app
    assert "/api/edit/lock_selection_tracks" in app
    assert "/api/edit/mute_selection_tracks" in app
    assert "def unlock_selection_tracks" in mcp
    assert "def lock_selection_tracks" in mcp
    assert "def mute_selection_tracks" in mcp
    assert 'id="btn-unlock-trk-sel"' in html
    assert 'id="btn-lock-trk-sel"' in html
    assert 'id="btn-mute-trk-sel"' in html
    assert 'id="btn-unmute-trk-sel"' in html
    assert "unlockSelectionTracksUi" in ts
    assert "lockSelectionTracksUi" in ts
    assert "muteSelectionTracksUi" in ts
