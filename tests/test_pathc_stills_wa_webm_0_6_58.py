"""export_selection_path_c_stills_plan_default + export_work_area_webm_default (0.6.58)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_pathc_stills_plan_and_wa_webm():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ps_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)

        plan = ed.export_selection_path_c_stills_plan_default(
            [c.id], filename="stills_plan.json", height=90,
        )
        p = Path(plan.get("path") or "")
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert int(data.get("adapter_version") or plan.get("adapter_version") or 0) >= int(
            ADAPTER_VERSION
        )

        ed.work_area_from_selection([c.id])
        wa = ed.export_work_area_webm_default(
            filename="wa.webm", crf=36, width=160,
        )
        wp = Path(
            wa.get("path")
            or wa.get("output_path")
            or (ed.bundle.root / "exports" / "wa.webm")
        )
        assert wp.is_file() or (ed.bundle.root / "exports" / "wa.webm").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_58():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_path_c_stills_plan_default" in app
    assert "/api/edit/export_work_area_webm_default" in app
    assert "def export_selection_path_c_stills_plan_default" in mcp
    assert "def export_work_area_webm_default" in mcp
    assert 'id="btn-pathc-stills-json"' in html
    assert 'id="btn-wa-webm-def"' in html
    assert "exportSelectionPathCStillsPlanDefaultUi" in ts
    assert "exportWorkAreaWebmDefaultUi" in ts
