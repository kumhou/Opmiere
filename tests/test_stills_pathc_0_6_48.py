"""export_selection_stills + selection_path_c_stills_plan (0.6.48)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=maroon:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_stills_and_pathc_plan():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sps_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 15)
        c2 = ed.add_clip(tr.id, med.id, 15, 0, 15)

        stills = ed.export_selection_stills(
            [c1.id, c2.id], edge="mid", width=80, ext="jpg",
        )
        assert stills["count"] == 2
        assert stills["error_count"] == 0
        for s in stills["stills"]:
            assert Path(s["path"]).is_file()

        plan = ed.selection_path_c_stills_plan([c1.id, c2.id], height=90)
        assert int(plan["adapter_version"]) >= int(ADAPTER_VERSION)
        assert plan["plan_clip_count"] >= 1
        assert "path_c_ready" in plan
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_48():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_stills" in app
    assert "/api/edit/selection_path_c_stills_plan" in app
    assert "def export_selection_stills" in mcp
    assert "def selection_path_c_stills_plan" in mcp
    assert 'id="btn-stills-sel"' in html
    assert 'id="btn-pathc-stills-sel"' in html
    assert "exportSelectionStillsUi" in ts
    assert "selectionPathCStillsPlanUi" in ts
