"""match_grade_to_clip + path-C lut3d."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _tiny_cube(path: Path) -> None:
    # Minimal identity 2x2x2 cube
    path.write_text(
        "TITLE \"id\"\n"
        "LUT_3D_SIZE 2\n"
        "0 0 0\n1 0 0\n0 1 0\n1 1 0\n"
        "0 0 1\n1 0 1\n0 1 1\n1 1 1\n",
        encoding="utf-8",
    )


def test_match_grade_to_clip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mg_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, 20)
        c3 = ed.place_from_file(v, "video", tr.id, 40)
        ed.apply_effect(c1.id, {"type": "vignette", "strength": 0.8})
        ed.apply_effect(c1.id, {"type": "curves", "preset": "vintage"})
        r = ed.match_grade_to_clip(c1.id, [c2.id, c3.id])
        assert r["count"] == 2
        types2 = [e.get("type") for e in ed._find_clip(c2.id).effects]
        assert "vignette" in types2
        assert "curves" in types2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_lut3d_mapped():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lut_"))
    try:
        v = root / "v.mp4"
        cube = root / "id.cube"
        _vid(v)
        _tiny_cube(cube)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "lut3d", "path": str(cube)})
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "lut3d" in vis["mapped_effects"]
        assert vis["lut3d"]["exists"] is True
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 17
        assert int(ADAPTER_VERSION) >= 17
        assert plan["clips"][0].get("lut3d", {}).get("exists") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_58():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clips/match_grade" in app
    assert "def match_grade_to_clip" in mcp
    assert 'id="btn-match-grade"' in html
    assert "matchGradeUi" in ts
