"""fit_selection_set_to_markers + snap_selection_set_to_markers (0.9.91)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_snap_and_fit_to_markers_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mkrfit_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 2, duration_frames=15)
        ed.save_selection_set("hero", [c.id])
        ed.add_marker(frame=0, label="A")
        ed.add_marker(frame=30, label="B")

        snap = ed.snap_selection_set_to_markers(
            "hero", edge="start", prefer="nearest",
        )
        assert snap.get("selection_set") == "hero"
        assert snap.get("count", 0) >= 1
        assert int(ed._find_clip(c.id).start) == 0

        # re-place slightly off marker for fit
        clip = ed._find_clip(c.id)
        with ed._mutate():
            clip.start = 1
        fit = ed.fit_selection_set_to_markers(
            "hero", method="speed", max_start_delta=8, clamp=True,
        )
        assert fit.get("selection_set") == "hero"
        fitted = fit.get("fitted") or fit.get("count")
        assert fitted is not None
        assert int(ed._find_clip(c.id).start) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_91():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/fit_selection_set_to_markers" in app
    assert "/api/edit/snap_selection_set_to_markers" in app
    assert "def fit_selection_set_to_markers" in mcp
    assert "def snap_selection_set_to_markers" in mcp
    assert 'id="btn-fit-markers-set"' in html
    assert 'id="btn-snap-markers-set"' in html
    assert "fitSelectionSetToMarkersUi" in ts
    assert "snapSelectionSetToMarkersUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "fit_selection_set_to_markers" in cat["tool_ids"]
    assert "snap_selection_set_to_markers" in cat["tool_ids"]
