"""match_frame_selection_set + ripple_trim_selection_set_edges (0.9.58)."""

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


def test_match_frame_and_ripple_trim_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mfrt_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        mf = ed.match_frame_selection_set("hero")
        assert mf.get("selection_set") == "hero"
        assert int(mf.get("count") or 0) >= 1

        rt = ed.ripple_trim_selection_set_edges(
            "hero", head_src_frames=0, tail_src_frames=1,
        )
        assert rt.get("selection_set") == "hero"
        assert rt.get("tail_src_frames") == 1
        assert "count" in rt
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_58():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/match_frame_selection_set" in app
    assert "/api/edit/ripple_trim_selection_set_edges" in app
    assert "def match_frame_selection_set" in mcp
    assert "def ripple_trim_selection_set_edges" in mcp
    assert 'id="btn-match-fr-set"' in html
    assert 'id="btn-rip-trim-set"' in html
    assert "matchFrameSelectionSetUi" in ts
    assert "rippleTrimSelectionSetEdgesUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "match_frame_selection_set" in cat["tool_ids"]
    assert "ripple_trim_selection_set_edges" in cat["tool_ids"]
