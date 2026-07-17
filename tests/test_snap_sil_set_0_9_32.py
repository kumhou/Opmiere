"""snap_selection_set_to_playhead + split_selection_set_at_silences (0.9.32)."""

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


def test_snap_and_silence_split_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sss2_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 10, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        snapped = ed.snap_selection_set_to_playhead("hero", 0)
        assert snapped.get("selection_set") == "hero"
        assert snapped.get("playhead_frame") == 0
        assert int(ed._find_clip(c.id).start) == 0

        # continuous sine may yield 0 splits; must not raise
        sil = ed.split_selection_set_at_silences("hero", max_splits=5)
        assert sil.get("selection_set") == "hero"
        assert "total_splits" in sil
        assert "error_count" in sil
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_32():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/snap_selection_set_to_playhead" in app
    assert "/api/edit/split_selection_set_at_silences" in app
    assert "def snap_selection_set_to_playhead" in mcp
    assert "def split_selection_set_at_silences" in mcp
    assert 'id="btn-snap-set"' in html
    assert 'id="btn-sil-split-set"' in html
    assert "snapSelectionSetToPlayheadUi" in ts
    assert "splitSelectionSetAtSilencesUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "snap_selection_set_to_playhead" in cat["tool_ids"]
    assert "split_selection_set_at_silences" in cat["tool_ids"]
