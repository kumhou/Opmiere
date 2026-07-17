"""batch_selection_sets_status + batch_run_selection_pipeline_preset (0.7.5)."""

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
            "-f", "lavfi", "-i", f"color=c=green:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=200:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_batch_status_and_batch_preset():
    root = Path(tempfile.mkdtemp(prefix="opmiere_batch_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, 8, duration_frames=8)
        ed.save_selection_set("a", [c1.id])
        ed.save_selection_set("b", [c2.id])
        ed.save_selection_pipeline_preset(
            "qc", ["validate", "checklist"],
        )

        batch = ed.batch_selection_sets_status(validate=True)
        assert batch.get("count") == 2
        assert batch.get("ok_count") == 2
        assert batch.get("fail_count") == 0
        names = {r["name"] for r in batch["results"]}
        assert names == {"a", "b"}

        run = ed.batch_run_selection_pipeline_preset(
            "qc",
            selection_sets=["a", "b"],
            dry_run=True,
        )
        assert run.get("preset") == "qc"
        assert run.get("dry_run") is True
        assert run.get("count") == 2
        assert run.get("ok_count") == 2
        assert run.get("fail_count") == 0
        assert all(r.get("ok") for r in run["results"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_5():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/batch_selection_sets_status" in app
    assert "/api/edit/batch_run_selection_pipeline_preset" in app
    assert "def batch_selection_sets_status" in mcp
    assert "def batch_run_selection_pipeline_preset" in mcp
    assert 'id="btn-batch-set-stat"' in html
    assert 'id="btn-batch-pipe"' in html
    assert "batchSelectionSetsStatusUi" in ts
    assert "batchRunSelectionPipelinePresetUi" in ts
