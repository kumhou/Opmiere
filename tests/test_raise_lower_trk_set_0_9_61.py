"""raise_selection_set_tracks + lower_selection_set_tracks (0.9.61)."""

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


def test_raise_and_lower_tracks_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rzlow_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr1 = ed.add_track("video")
        tr2 = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr1.id, 0, duration_frames=12)
        ed.place_from_file(v, "video", tr2.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        up = ed.raise_selection_set_tracks("hero", steps=1)
        assert up.get("selection_set") == "hero"
        assert "count" in up
        assert "order" in up

        down = ed.lower_selection_set_tracks("hero", steps=1)
        assert down.get("selection_set") == "hero"
        assert "count" in down
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_61():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/raise_selection_set_tracks" in app
    assert "/api/edit/lower_selection_set_tracks" in app
    assert "def raise_selection_set_tracks" in mcp
    assert "def lower_selection_set_tracks" in mcp
    assert 'id="btn-raise-trk-set"' in html
    assert 'id="btn-lower-trk-set"' in html
    assert "raiseSelectionSetTracksUi" in ts
    assert "lowerSelectionSetTracksUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "raise_selection_set_tracks" in cat["tool_ids"]
    assert "lower_selection_set_tracks" in cat["tool_ids"]
