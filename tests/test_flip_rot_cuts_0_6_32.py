"""flip_selection + rotate_selection + selection_cut_report (0.6.32)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=lime:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_flip_rot_cuts():
    root = Path(tempfile.mkdtemp(prefix="opmiere_frc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 10, 0, 10)
        c3 = ed.add_clip(tr.id, med.id, 25, 0, 10)

        fl = ed.flip_selection([c1.id], horizontal=True)
        assert fl.get("count") or any(
            e.get("type") == "hflip"
            for e in (ed._find_clip(c1.id).effects or [])
            if isinstance(e, dict)
        )
        assert any(
            isinstance(e, dict) and e.get("type") == "hflip"
            for e in (ed._find_clip(c1.id).effects or [])
        )

        rt = ed.rotate_selection([c2.id], 90)
        assert rt["count"] == 1
        assert any(
            isinstance(e, dict) and e.get("type") == "rotate"
            for e in (ed._find_clip(c2.id).effects or [])
        )

        cuts = ed.selection_cut_report([c1.id, c2.id, c3.id])
        assert cuts["count"] == 2
        kinds = {p["kind"] for p in cuts["pairs"]}
        assert "hard_cut" in kinds
        assert "gap" in kinds
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_32():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/flip_selection" in app
    assert "/api/edit/rotate_selection" in app
    assert "/api/edit/selection_cut_report" in app
    assert "def flip_selection" in mcp
    assert "def rotate_selection" in mcp
    assert "def selection_cut_report" in mcp
    assert 'id="btn-flip-h-sel"' in html
    assert 'id="btn-rot90-sel"' in html
    assert 'id="btn-cuts-sel"' in html
    assert "flipSelectionHUi" in ts
    assert "rotateSelectionUi" in ts
    assert "selectionCutReportUi" in ts
