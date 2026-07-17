"""duplicate_selection_set_block + align_selection_set_ends (0.9.59)."""

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


def test_dup_block_and_align_ends_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dupalign_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 20, duration_frames=8)
        ed.save_selection_set("hero", [c1.id, c2.id])

        dup = ed.duplicate_selection_set_block("hero", gap_frames=0)
        assert dup.get("selection_set") == "hero"
        assert int(dup.get("count") or 0) >= 1

        al = ed.align_selection_set_ends("hero")
        assert al.get("selection_set") == "hero"
        assert "to_frame" in al
        assert "count" in al
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_59():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/duplicate_selection_set_block" in app
    assert "/api/edit/align_selection_set_ends" in app
    assert "def duplicate_selection_set_block" in mcp
    assert "def align_selection_set_ends" in mcp
    assert 'id="btn-dup-block-set"' in html
    assert 'id="btn-align-ends-set"' in html
    assert "duplicateSelectionSetBlockUi" in ts
    assert "alignSelectionSetEndsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "duplicate_selection_set_block" in cat["tool_ids"]
    assert "align_selection_set_ends" in cat["tool_ids"]
