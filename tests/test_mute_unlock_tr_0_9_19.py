"""mute_selection_set_tracks + unlock_selection_set_tracks (0.9.19)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_mute_and_unlock_tracks_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mut_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        muted = ed.mute_selection_set_tracks("hero", muted=True)
        assert muted.get("selection_set") == "hero"
        assert muted.get("muted") is True
        tr_rep = ed.selection_set_track_report("hero")
        assert tr_rep.get("muted_count", 0) >= 1

        ed.lock_selection_set_tracks("hero")
        unlocked = ed.unlock_selection_set_tracks("hero")
        assert unlocked.get("selection_set") == "hero"
        locks = ed.selection_set_locked_tracks("hero")
        assert locks.get("locked_count", 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_19():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/mute_selection_set_tracks" in app
    assert "/api/edit/unlock_selection_set_tracks" in app
    assert "def mute_selection_set_tracks" in mcp
    assert "def unlock_selection_set_tracks" in mcp
    assert 'id="btn-mute-set-tr"' in html
    assert 'id="btn-unlock-set-tr"' in html
    assert "muteSelectionSetTracksUi" in ts
    assert "unlockSelectionSetTracksUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "mute_selection_set_tracks" in cat["tool_ids"]
    assert "unlock_selection_set_tracks" in cat["tool_ids"]
