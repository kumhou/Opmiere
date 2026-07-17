"""selection_set_fades_report + selection_set_transition_report (0.9.9)."""

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


def test_fades_and_transition_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sfx_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        fades = ed.selection_set_fades_report("hero")
        assert fades.get("selection_set") == "hero"
        assert fades.get("clip_count") == 1
        assert fades.get("with_fades", 0) == 0

        x = ed.selection_set_transition_report("hero")
        assert x.get("selection_set") == "hero"
        assert x.get("clip_count") == 1
        assert x.get("with_transitions", 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_9():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_fades_report" in app
    assert "/api/edit/selection_set_transition_report" in app
    assert "def selection_set_fades_report" in mcp
    assert "def selection_set_transition_report" in mcp
    assert 'id="btn-set-fades"' in html
    assert 'id="btn-set-x"' in html
    assert "selectionSetFadesReportUi" in ts
    assert "selectionSetTransitionReportUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_fades_report" in cat["tool_ids"]
    assert "selection_set_transition_report" in cat["tool_ids"]
