"""export_selection_set_path_c_stills_plan + match_frame_selection_set (0.9.87)."""

from __future__ import annotations

import json
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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_path_c_stills_export_and_match_frame_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_stmf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        exp = ed.export_selection_set_path_c_stills_plan("hero", height=180)
        assert exp.get("selection_set") == "hero"
        path = exp.get("path")
        assert path and Path(str(path)).is_file()
        data = json.loads(Path(str(path)).read_text(encoding="utf-8"))
        assert isinstance(data, dict)

        mf = ed.match_frame_selection_set("hero")
        assert mf.get("selection_set") == "hero"
        assert mf.get("count", 0) + mf.get("error_count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_87():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_path_c_stills_plan" in app
    assert "/api/edit/match_frame_selection_set" in app
    assert "def export_selection_set_path_c_stills_plan" in mcp
    assert "def match_frame_selection_set" in mcp
    assert 'id="btn-exp-path-c-stills-set"' in html
    assert 'id="btn-match-frame-set"' in html
    assert "exportSelectionSetPathCStillsPlanUi" in ts
    assert "matchFrameSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_path_c_stills_plan" in cat["tool_ids"]
    assert "match_frame_selection_set" in cat["tool_ids"]
