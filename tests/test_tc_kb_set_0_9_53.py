"""timecode_selection_set + ken_burns_selection_set (0.9.53)."""

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


def test_timecode_and_ken_burns_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_tckb_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        tc = ed.timecode_selection_set("hero", position="bottom", size=28)
        assert tc.get("selection_set") == "hero"
        assert tc.get("position") == "bottom"
        assert "count" in tc

        kb = ed.ken_burns_selection_set(
            "hero", zoom_start=1.0, zoom_end=1.2, replace=True,
        )
        assert kb.get("selection_set") == "hero"
        assert kb.get("zoom_end") == 1.2
        assert "count" in kb
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_53():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/timecode_selection_set" in app
    assert "/api/edit/ken_burns_selection_set" in app
    assert "def timecode_selection_set" in mcp
    assert "def ken_burns_selection_set" in mcp
    assert 'id="btn-tc-set"' in html
    assert 'id="btn-kb-set"' in html
    assert "timecodeSelectionSetUi" in ts
    assert "kenBurnsSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "timecode_selection_set" in cat["tool_ids"]
    assert "ken_burns_selection_set" in cat["tool_ids"]
