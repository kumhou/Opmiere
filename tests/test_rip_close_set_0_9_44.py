"""ripple_nudge_selection_set + close_gaps_on_selection_set_tracks (0.9.44)."""

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


def test_ripple_nudge_and_close_gaps_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 20, duration_frames=12)
        ed.save_selection_set("hero", [c1.id, c2.id])

        rip = ed.ripple_nudge_selection_set("hero", 6)
        assert rip.get("selection_set") == "hero"
        assert rip.get("delta_frames") == 6
        assert rip.get("count", 0) >= 1
        assert int(ed._find_clip(c1.id).start) == 6

        closed = ed.close_gaps_on_selection_set_tracks("hero")
        assert closed.get("selection_set") == "hero"
        assert closed.get("count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_44():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/ripple_nudge_selection_set" in app
    assert "/api/edit/close_gaps_on_selection_set_tracks" in app
    assert "def ripple_nudge_selection_set" in mcp
    assert "def close_gaps_on_selection_set_tracks" in mcp
    assert 'id="btn-rip-nudge-set"' in html
    assert 'id="btn-close-gaps-set"' in html
    assert "rippleNudgeSelectionSetUi" in ts
    assert "closeGapsOnSelectionSetTracksUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "ripple_nudge_selection_set" in cat["tool_ids"]
    assert "close_gaps_on_selection_set_tracks" in cat["tool_ids"]
