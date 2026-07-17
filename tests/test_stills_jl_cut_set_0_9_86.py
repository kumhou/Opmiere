"""selection_set_path_c_stills_plan + selection_set_jl_cut (0.9.86)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_stills_plan_and_jl_cut_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_stjl_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        plan = ed.selection_set_path_c_stills_plan("hero", height=180)
        assert plan.get("selection_set") == "hero"
        assert "plan" in plan or plan.get("plan_clip_count") is not None
        assert plan.get("adapter_version") is not None

        jl = ed.selection_set_jl_cut("hero", style="j", frames=4, link=True)
        assert jl.get("selection_set") == "hero"
        assert jl.get("style") in ("j", "l")
        assert jl.get("frames") == 4
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_86():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_path_c_stills_plan" in app
    assert "/api/edit/selection_set_jl_cut" in app
    assert "def selection_set_path_c_stills_plan" in mcp
    assert "def selection_set_jl_cut" in mcp
    assert 'id="btn-path-c-stills-set"' in html
    assert 'id="btn-jl-cut-set"' in html
    assert "selectionSetPathCStillsPlanUi" in ts
    assert "selectionSetJlCutUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_path_c_stills_plan" in cat["tool_ids"]
    assert "selection_set_jl_cut" in cat["tool_ids"]
