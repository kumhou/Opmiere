"""save/run selection_pipeline_preset (0.7.2)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=white:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=280:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_save_list_run_delete_pipeline_preset():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        saved = ed.save_selection_pipeline_preset(
            "qc",
            ["validate", "checklist"],
            note="quick check",
        )
        assert saved.get("ok") is True
        assert saved["steps"] == ["validate", "checklist"]
        assert Path(saved["path"]).is_file()

        listed = ed.list_selection_pipeline_presets()
        assert listed["count"] == 1
        assert listed["presets"][0]["name"] == "qc"

        dry = ed.run_selection_pipeline_preset(
            "qc",
            clip_ids=[c.id],
            dry_run=True,
        )
        assert dry.get("preset") == "qc"
        assert dry.get("dry_run") is True
        assert dry.get("ok") is True
        assert "validate" in dry["executed"]

        ed.save_selection_set("hero", [c.id])
        dry2 = ed.run_selection_pipeline_preset(
            "qc",
            selection_set="hero",
            dry_run=True,
        )
        assert dry2.get("loaded", {}).get("selection_set") == "hero"

        deleted = ed.delete_selection_pipeline_preset("qc")
        assert deleted.get("ok") is True
        assert ed.list_selection_pipeline_presets()["count"] == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_2():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/save_selection_pipeline_preset" in app
    assert "/api/edit/run_selection_pipeline_preset" in app
    assert "/api/edit/list_selection_pipeline_presets" in app
    assert "def save_selection_pipeline_preset" in mcp
    assert "def run_selection_pipeline_preset" in mcp
    assert 'id="btn-save-pipe-pre"' in html
    assert 'id="btn-run-pipe-pre"' in html
    assert "saveSelectionPipelinePresetUi" in ts
    assert "runSelectionPipelinePresetUi" in ts
