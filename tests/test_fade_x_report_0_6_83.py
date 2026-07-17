"""selection_fades_report + selection_transition_report (0.6.83)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=540:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_fades_and_transition_reports():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fxr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.6)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 12, duration_frames=12)

        ed.set_selection_fades([c1.id], fade_in_frames=3, fade_out_frames=3)
        fr = ed.selection_fades_report([c1.id, c2.id])
        assert int(fr.get("count") or 0) == 2
        assert int(fr.get("with_fades") or 0) >= 1

        # hard cuts: no transitions by default
        xr = ed.selection_transition_report([c1.id, c2.id])
        assert int(xr.get("count") or 0) == 2
        assert int(xr.get("with_transitions") or 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_83():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_fades_report" in app
    assert "/api/edit/selection_transition_report" in app
    assert "def selection_fades_report" in mcp
    assert "def selection_transition_report" in mcp
    assert 'id="btn-fade-rep-sel"' in html
    assert 'id="btn-x-rep-sel"' in html
    assert "selectionFadesReportUi" in ts
    assert "selectionTransitionReportUi" in ts
