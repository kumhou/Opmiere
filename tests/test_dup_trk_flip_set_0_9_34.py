"""duplicate_selection_set_to_track + set_selection_set_flip (0.9.34)."""

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


def test_dup_to_track_and_flip_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dtf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr1 = ed.add_track("video")
        tr2 = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr1.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        dup = ed.duplicate_selection_set_to_track("hero", tr2.id)
        assert dup.get("selection_set") == "hero"
        assert dup.get("track_id") == tr2.id
        assert dup.get("count", 0) >= 1
        assert len(tr2.clips) >= 1

        flip = ed.set_selection_set_flip("hero", horizontal=True)
        assert flip.get("selection_set") == "hero"
        assert flip.get("count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_34():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/duplicate_selection_set_to_track" in app
    assert "/api/edit/set_selection_set_flip" in app
    assert "def duplicate_selection_set_to_track" in mcp
    assert "def set_selection_set_flip" in mcp
    assert 'id="btn-dup-trk-set"' in html
    assert 'id="btn-flip-set"' in html
    assert "duplicateSelectionSetToTrackUi" in ts
    assert "setSelectionSetFlipUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "duplicate_selection_set_to_track" in cat["tool_ids"]
    assert "set_selection_set_flip" in cat["tool_ids"]
