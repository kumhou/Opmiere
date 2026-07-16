"""crop_selection_center + vignette_selection + selection_effects_report (0.6.33)."""

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
            "-f", "lavfi", "-i", f"color=c=cyan:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_crop_vig_fx_report():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cvf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 15)
        c2 = ed.add_clip(tr.id, med.id, 15, 0, 15)

        cr = ed.crop_selection_center([c1.id], scale=0.85)
        assert cr["count"] == 1
        assert cr["width"] == 136  # 160*0.85 even
        assert any(
            isinstance(e, dict) and e.get("type") == "crop"
            for e in (ed._find_clip(c1.id).effects or [])
        )

        vg = ed.vignette_selection([c1.id, c2.id], strength=0.35)
        assert vg["count"] == 2
        assert any(
            isinstance(e, dict) and e.get("type") == "vignette"
            for e in (ed._find_clip(c2.id).effects or [])
        )

        fx = ed.selection_effects_report([c1.id, c2.id])
        assert int(fx["adapter_version"]) >= int(ADAPTER_VERSION)
        assert fx["count"] == 2
        assert fx["histogram"].get("vignette", 0) >= 1
        assert "crop" in fx["histogram"] or any(
            "crop" in (row.get("effects") or []) for row in fx["clips"]
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_33():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/crop_selection_center" in app
    assert "/api/edit/vignette_selection" in app
    assert "/api/edit/selection_effects_report" in app
    assert "def crop_selection_center" in mcp
    assert "def vignette_selection" in mcp
    assert "def selection_effects_report" in mcp
    assert 'id="btn-crop-sel"' in html
    assert 'id="btn-vig-sel"' in html
    assert 'id="btn-fx-sel"' in html
    assert "cropSelectionCenterUi" in ts
    assert "vignetteSelectionUi" in ts
    assert "selectionEffectsReportUi" in ts
