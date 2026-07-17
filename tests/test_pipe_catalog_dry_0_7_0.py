"""selection_pipeline_catalog + dry_run_selection_pipeline (0.7.0)."""

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
            "-f", "lavfi", "-i", f"color=c=gray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=360:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_catalog_and_dry_run():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dry_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        cat = ed.selection_pipeline_catalog()
        assert cat.get("ok") is True
        assert "validate" in cat["step_ids"]
        assert "export_mp4" in cat["step_ids"]
        assert cat["default_plan"][0] == "validate"

        dry = ed.dry_run_selection_pipeline(
            [c.id],
            steps=["validate", "repair", "export_mp4", "checklist"],
            execute_read_only=True,
        )
        assert dry.get("dry_run") is True
        assert dry.get("ok") is True
        assert "validate" in dry["executed"]
        assert "checklist" in dry["executed"]
        assert "repair" in dry["would_execute"]
        assert "export_mp4" in dry["would_execute"]
        # no export file from dry-run
        exports = Path(ed.bundle.root) / "exports"
        if exports.is_dir():
            mp4s = list(exports.glob("**/*.mp4"))
            assert not any("pipeline" in p.name for p in mp4s)

        # unknown step fails dry-run ok
        bad = ed.dry_run_selection_pipeline([c.id], steps=["nope"])
        assert bad.get("ok") is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_0():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_pipeline_catalog" in app
    assert "/api/edit/dry_run_selection_pipeline" in app
    assert "def selection_pipeline_catalog" in mcp
    assert "def dry_run_selection_pipeline" in mcp
    assert 'id="btn-pipe-cat"' in html
    assert 'id="btn-pipe-dry"' in html
    assert "selectionPipelineCatalogUi" in ts
    assert "dryRunSelectionPipelineUi" in ts
