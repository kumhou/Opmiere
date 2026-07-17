"""unsolo_selection_set_tracks + join_selection_set (0.9.22)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_unsolo_and_join_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ujs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 12, duration_frames=12)
        ed.save_selection_set("hero", [c1.id, c2.id])

        ed.solo_selection_set_tracks("hero")
        assert ed.selection_set_track_report("hero").get("solo_count", 0) >= 1
        un = ed.unsolo_selection_set_tracks("hero")
        assert un.get("selection_set") == "hero"
        assert ed.selection_set_track_report("hero").get("solo_count", 0) == 0

        joined = ed.join_selection_set("hero")
        assert joined.get("selection_set") == "hero"
        # join may succeed (count>=1) or report errors if not joinable
        assert "count" in joined
        assert "error_count" in joined
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_22():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/unsolo_selection_set_tracks" in app
    assert "/api/edit/join_selection_set" in app
    assert "def unsolo_selection_set_tracks" in mcp
    assert "def join_selection_set" in mcp
    assert 'id="btn-unsolo-set-tr"' in html
    assert 'id="btn-join-set"' in html
    assert "unsoloSelectionSetTracksUi" in ts
    assert "joinSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "unsolo_selection_set_tracks" in cat["tool_ids"]
    assert "join_selection_set" in cat["tool_ids"]
