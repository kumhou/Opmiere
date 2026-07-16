"""match_frame_selection + ripple_trim_selection_edges + export path-C plan (0.6.27)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=coral:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_match_rtrim_export_pathc():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mrp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 20)
        c2 = ed.add_clip(tr.id, med.id, 20, 20, 40)

        mf = ed.match_frame_selection([c1.id, c2.id], timeline_frame=5)
        assert mf["count"] == 2
        assert mf["matches"][0]["clip_id"] == c1.id
        assert "src_frame" in mf["matches"][0]

        # ripple trim head of c2 by 2 source frames → c2 starts later? 
        # ripple_trim shortens; c2 after c1 adjacent
        rt = ed.ripple_trim_selection_edges([c1.id], head_src_frames=0, tail_src_frames=3)
        assert rt["count"] == 1
        assert ed._find_clip(c1.id).src_out == 17
        # c2 should have shifted left by 3
        assert ed._find_clip(c2.id).start == 17

        out = root / "plan.json"
        exp = ed.export_selection_path_c_plan([c1.id, c2.id], out, height=360)
        assert out.is_file()
        assert int(exp["adapter_version"]) >= int(ADAPTER_VERSION)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data.get("clips") or []) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_27():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/match_frame_selection" in app
    assert "/api/edit/ripple_trim_selection_edges" in app
    assert "/api/edit/export_selection_path_c_plan" in app
    assert "def match_frame_selection" in mcp
    assert "def ripple_trim_selection_edges" in mcp
    assert "def export_selection_path_c_plan" in mcp
    assert 'id="btn-match-sel"' in html
    assert 'id="btn-rtrim-h-sel"' in html
    assert 'id="btn-rtrim-t-sel"' in html
    assert 'id="btn-export-pathc-sel"' in html
    assert "matchFrameSelectionUi" in ts
    assert "rippleTrimSelectionEdgesUi" in ts
    assert "exportSelectionPathCPlanUi" in ts
