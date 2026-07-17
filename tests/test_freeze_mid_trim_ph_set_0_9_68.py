"""freeze_selection_set_mids + trim_selection_set_to_playhead (0.9.68)."""

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


def test_freeze_mids_and_trim_playhead_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fzmid_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        # trim first (lighter); freeze may re-encode still
        trm = ed.trim_selection_set_to_playhead(
            "hero", playhead_frame=6, edge="head", mode="normal",
        )
        assert trm.get("selection_set") == "hero"
        assert trm.get("playhead_frame") == 6
        assert "count" in trm

        # re-save after trim; clip may still span mid for freeze
        clip = ed._find_clip(c.id)
        ed.save_selection_set("hero", [clip.id])
        fr = ed.freeze_selection_set_mids(
            "hero", duration_frames=6, insert=True,
        )
        assert fr.get("selection_set") == "hero"
        assert "count" in fr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_68():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/freeze_selection_set_mids" in app
    assert "/api/edit/trim_selection_set_to_playhead" in app
    assert "def freeze_selection_set_mids" in mcp
    assert "def trim_selection_set_to_playhead" in mcp
    assert 'id="btn-freeze-mid-set"' in html
    assert 'id="btn-trim-ph-set"' in html
    assert "freezeSelectionSetMidsUi" in ts
    assert "trimSelectionSetToPlayheadUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "freeze_selection_set_mids" in cat["tool_ids"]
    assert "trim_selection_set_to_playhead" in cat["tool_ids"]
