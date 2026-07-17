"""rename/copy selection_pipeline_preset (0.7.4)."""

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
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=220:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_rename_and_copy_pipeline_preset():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pprc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)

        ed.save_selection_pipeline_preset(
            "draft", ["validate", "checklist"], note="wip",
        )
        copied = ed.copy_selection_pipeline_preset(
            "draft", "draft_bak", overwrite=True,
        )
        assert copied.get("ok") is True
        assert copied.get("dest") == "draft_bak"
        assert copied["steps"] == ["validate", "checklist"]

        ren = ed.rename_selection_pipeline_preset(
            "draft", "qc", overwrite=False,
        )
        assert ren.get("ok") is True
        assert ren.get("old_name") == "draft"
        assert ren.get("new_name") == "qc"

        names = {
            p["name"] for p in ed.list_selection_pipeline_presets()["presets"]
        }
        assert "draft" not in names
        assert "qc" in names
        assert "draft_bak" in names
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_4():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/rename_selection_pipeline_preset" in app
    assert "/api/edit/copy_selection_pipeline_preset" in app
    assert "def rename_selection_pipeline_preset" in mcp
    assert "def copy_selection_pipeline_preset" in mcp
    assert 'id="btn-ren-pipe-pre"' in html
    assert 'id="btn-copy-pipe-pre"' in html
    assert "renameSelectionPipelinePresetUi" in ts
    assert "copySelectionPipelinePresetUi" in ts
