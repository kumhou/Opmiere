"""extend_selection_to_next + set_selection_speed + selection_path_c_plan (0.6.26)."""

from __future__ import annotations

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
            "-f", "lavfi", "-i", f"color=c=purple:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_extnext_speed_pathc():
    root = Path(tempfile.mkdtemp(prefix="opmiere_esp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)  # ~60f
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 20, 20, 30)
        # gap 10f; c1 has remaining source after src_out=10
        ex = ed.extend_selection_to_next([c1.id])
        assert ex["count"] == 1
        assert ed._find_clip(c1.id).end == 20
        assert ed._find_clip(c1.id).src_out == 20

        sp = ed.set_selection_speed([c2.id], 2.0)
        assert sp["count"] == 1
        assert abs(ed._find_clip(c2.id).speed - 2.0) < 1e-9

        plan = ed.selection_path_c_plan([c1.id, c2.id], height=360)
        assert int(plan["adapter_version"]) >= int(ADAPTER_VERSION)
        assert plan.get("selection_span")
        ids = {e.get("id") for e in (plan.get("clips") or [])}
        assert c1.id in ids
        assert c2.id in ids
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_26():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/extend_selection_next" in app
    assert "/api/edit/selection_speed" in app
    assert "/api/edit/selection_path_c_plan" in app
    assert "def extend_selection_to_next" in mcp
    assert "def set_selection_speed" in mcp
    assert "def selection_path_c_plan" in mcp
    assert 'id="btn-ext-next-sel"' in html
    assert 'id="btn-speed1-sel"' in html
    assert 'id="btn-speed2-sel"' in html
    assert 'id="btn-pathc-plan-sel"' in html
    assert "extendSelectionNextUi" in ts
    assert "selectionSpeedUi" in ts
    assert "selectionPathCPlanUi" in ts
