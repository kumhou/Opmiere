"""align_selection_ends + selection_media_report + rename_from_media (0.6.29)."""

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
            "-f", "lavfi", "-i", f"color=c=gold:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_align_media_rename():
    root = Path(tempfile.mkdtemp(prefix="opmiere_amn_"))
    try:
        v = root / "shot_alpha.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 5, 0, 20)

        al = ed.align_selection_ends([c1.id, c2.id])
        assert ed._find_clip(c1.id).end == ed._find_clip(c2.id).end
        assert al["to_frame"] == ed._find_clip(c2.id).end

        rep = ed.selection_media_report([c1.id, c2.id])
        assert rep["count"] == 2
        assert rep["media_count"] == 1
        assert rep["media"][0]["count"] == 2
        assert "shot_alpha" in rep["media"][0]["path"] or "shot_alpha" in Path(
            rep["media"][0]["path"]
        ).name

        stem = Path(med.path).stem
        rn = ed.rename_selection_from_media([c1.id, c2.id])
        assert rn["count"] == 2
        assert ed._find_clip(c1.id).name == stem
        assert ed._find_clip(c2.id).name == stem
        assert "shot_alpha" in stem
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_29():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/align_selection_ends" in app
    assert "/api/edit/selection_media_report" in app
    assert "/api/edit/rename_selection_from_media" in app
    assert "def align_selection_ends" in mcp
    assert "def selection_media_report" in mcp
    assert "def rename_selection_from_media" in mcp
    assert 'id="btn-align-ends-sel"' in html
    assert 'id="btn-media-sel"' in html
    assert 'id="btn-rename-media-sel"' in html
    assert "alignSelectionEndsUi" in ts
    assert "selectionMediaReportUi" in ts
    assert "renameSelectionFromMediaUi" in ts
