"""selection_set_status + dry_run_selection_set_pipeline (0.7.1)."""

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
            "-f", "lavfi", "-i", f"color=c=black:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=300:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_status_and_set_dry_run():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ssd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        ed.save_selection_set("hero", [c.id], note="h")

        st = ed.selection_set_status("hero", validate=True)
        assert st.get("name") == "hero"
        assert st.get("clip_count") == 1
        assert st.get("missing_count") == 0
        assert st.get("empty") is False
        assert st.get("span") is not None
        assert st.get("validate") is not None

        dry = ed.dry_run_selection_set_pipeline(
            "hero",
            steps=["validate", "export_mp4", "checklist"],
            execute_read_only=True,
        )
        assert dry.get("dry_run") is True
        assert dry.get("selection_set") == "hero"
        assert "validate" in dry["executed"]
        assert "export_mp4" in dry["would_execute"]
        assert (dry.get("loaded") or {}).get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_1():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_status" in app
    assert "/api/edit/dry_run_selection_set_pipeline" in app
    assert "def selection_set_status" in mcp
    assert "def dry_run_selection_set_pipeline" in mcp
    assert 'id="btn-set-stat"' in html
    assert 'id="btn-set-dry"' in html
    assert "selectionSetStatusUi" in ts
    assert "dryRunSelectionSetPipelineUi" in ts
