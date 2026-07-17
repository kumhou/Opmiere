"""export/import selection_pipeline_presets (0.7.3)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=silver:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=250:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_import_pipeline_presets_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ppi_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)

        ed.save_selection_pipeline_preset(
            "qc", ["validate", "checklist"], note="quick",
        )
        ed.save_selection_pipeline_preset(
            "ship", ["validate", "repair", "export_mp4", "checklist"],
        )

        exp = ed.export_selection_pipeline_presets()
        assert exp.get("ok") is True
        assert exp.get("count") == 2
        path = Path(exp["path"])
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "qc" in data["presets"] and "ship" in data["presets"]

        ed.delete_selection_pipeline_preset("qc")
        ed.delete_selection_pipeline_preset("ship")
        assert ed.list_selection_pipeline_presets()["count"] == 0

        imp = ed.import_selection_pipeline_presets(
            path, mode="merge", overwrite=True, validate_steps=True,
        )
        assert imp.get("ok") is True
        assert imp.get("imported_count") == 2
        names = {p["name"] for p in ed.list_selection_pipeline_presets()["presets"]}
        assert names == {"qc", "ship"}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_3():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_pipeline_presets" in app
    assert "/api/edit/import_selection_pipeline_presets" in app
    assert "def export_selection_pipeline_presets" in mcp
    assert "def import_selection_pipeline_presets" in mcp
    assert 'id="btn-exp-pipe-pre"' in html
    assert 'id="btn-imp-pipe-pre"' in html
    assert "exportSelectionPipelinePresetsUi" in ts
    assert "importSelectionPipelinePresetsUi" in ts
