"""selection_set_path_c_report + selection_set_locked_tracks (0.9.7)."""

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
            "-f", "lavfi", "-i", f"color=c=midnightblue:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_path_c_and_locked_tracks():
    root = Path(tempfile.mkdtemp(prefix="opmiere_spl_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        pc = ed.selection_set_path_c_report("hero")
        assert pc.get("selection_set") == "hero"
        assert pc.get("clip_count") == 1
        assert "not_ready_count" in pc or "path_c_ready" in pc or "rows" in pc

        locks = ed.selection_set_locked_tracks("hero")
        assert locks.get("selection_set") == "hero"
        assert locks.get("locked_count", 0) == 0
        assert locks.get("unlocked_count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_7():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_path_c_report" in app
    assert "/api/edit/selection_set_locked_tracks" in app
    assert "def selection_set_path_c_report" in mcp
    assert "def selection_set_locked_tracks" in mcp
    assert 'id="btn-set-pathc"' in html
    assert 'id="btn-set-locks"' in html
    assert "selectionSetPathCReportUi" in ts
    assert "selectionSetLockedTracksUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_path_c_report" in cat["tool_ids"]
    assert "selection_set_locked_tracks" in cat["tool_ids"]
