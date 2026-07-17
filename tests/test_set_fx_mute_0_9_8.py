"""selection_set_effects_report + selection_set_muted_report (0.9.8)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_effects_and_muted_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sfm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        fx = ed.selection_set_effects_report("hero")
        assert fx.get("selection_set") == "hero"
        assert fx.get("clip_count") == 1

        muted = ed.selection_set_muted_report("hero")
        assert muted.get("selection_set") == "hero"
        assert muted.get("muted_count", 0) == 0
        assert muted.get("clip_count") == 1 or muted.get("count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_8():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_effects_report" in app
    assert "/api/edit/selection_set_muted_report" in app
    assert "def selection_set_effects_report" in mcp
    assert "def selection_set_muted_report" in mcp
    assert 'id="btn-set-fx"' in html
    assert 'id="btn-set-mute"' in html
    assert "selectionSetEffectsReportUi" in ts
    assert "selectionSetMutedReportUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_effects_report" in cat["tool_ids"]
    assert "selection_set_muted_report" in cat["tool_ids"]
