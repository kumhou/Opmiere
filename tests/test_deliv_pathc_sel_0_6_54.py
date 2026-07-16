"""delivery_check_selection + export_selection_path_c_plan_default (0.6.54)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 0.4) -> None:
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


def test_delivery_and_pathc_plan_default():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        plan = ed.export_selection_path_c_plan_default(
            [c.id], filename="pc.json", height=90,
        )
        p = Path(plan.get("output_path") or plan.get("path") or "")
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert int(data.get("adapter_version") or plan.get("adapter_version") or 0) >= int(
            ADAPTER_VERSION
        )

        deliv = ed.delivery_check_selection(
            [c.id], filename="sel_deliv.mp4", preset="streaming",
        )
        ep = Path(deliv.get("export_path") or "")
        assert ep.is_file() or (ed.bundle.root / "exports" / "sel_deliv.mp4").is_file()
        assert "selection_span" in deliv or deliv.get("export_path")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_54():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/delivery_check_selection" in app
    assert "/api/edit/export_selection_path_c_plan_default" in app
    assert "def delivery_check_selection" in mcp
    assert "def export_selection_path_c_plan_default" in mcp
    assert 'id="btn-deliv-sel"' in html
    assert 'id="btn-pathc-json-sel"' in html
    assert "deliveryCheckSelectionUi" in ts
    assert "exportSelectionPathCPlanDefaultUi" in ts
