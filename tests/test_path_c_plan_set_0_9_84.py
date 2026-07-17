"""selection_set_path_c_plan + export_selection_set_path_c_plan (0.9.84)."""

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


def test_path_c_plan_and_export_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pathc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        plan = ed.selection_set_path_c_plan("hero", height=180)
        assert plan.get("selection_set") == "hero"
        assert plan.get("selection_span") or plan.get("clip_ids")
        clips = plan.get("clips") or []
        assert isinstance(clips, list)

        exp = ed.export_selection_set_path_c_plan("hero", height=180)
        assert exp.get("selection_set") == "hero"
        out = exp.get("output_path")
        assert out and Path(str(out)).is_file()
        data = json.loads(Path(str(out)).read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "clips" in data or "selection_clip_ids" in data
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_84():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_path_c_plan" in app
    assert "/api/edit/export_selection_set_path_c_plan" in app
    assert "def selection_set_path_c_plan" in mcp
    assert "def export_selection_set_path_c_plan" in mcp
    assert 'id="btn-path-c-plan-set"' in html
    assert 'id="btn-exp-path-c-plan-set"' in html
    assert "selectionSetPathCPlanUi" in ts
    assert "exportSelectionSetPathCPlanUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_path_c_plan" in cat["tool_ids"]
    assert "export_selection_set_path_c_plan" in cat["tool_ids"]
