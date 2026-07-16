"""raise/lower/rename selection tracks (0.6.47)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_raise_lower_rename_tracks():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rln_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr0 = ed.add_track("video")
        tr1 = ed.add_track("video")
        tr2 = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr1.id, med.id, 0, 0, 8)

        order0 = [t.id for t in ed.project.tracks]
        assert order0.index(tr1.id) == 1

        up = ed.raise_selection_tracks([c1.id], steps=1)
        order1 = [t.id for t in ed.project.tracks]
        assert order1.index(tr1.id) == 2
        assert tr2.id in up["order"]

        dn = ed.lower_selection_tracks([c1.id], steps=1)
        order2 = [t.id for t in ed.project.tracks]
        assert order2.index(tr1.id) == 1
        assert dn["steps"] == 1

        rn = ed.rename_selection_tracks([c1.id], prefix="Sel-")
        assert rn["count"] == 1
        assert ed.project.track_by_id(tr1.id).name == f"Sel-{tr1.id}"
        assert tr0.id in order2  # still present
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_47():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/raise_selection_tracks" in app
    assert "/api/edit/lower_selection_tracks" in app
    assert "/api/edit/rename_selection_tracks" in app
    assert "def raise_selection_tracks" in mcp
    assert "def lower_selection_tracks" in mcp
    assert "def rename_selection_tracks" in mcp
    assert 'id="btn-raise-trk-sel"' in html
    assert 'id="btn-lower-trk-sel"' in html
    assert 'id="btn-rename-trk-sel"' in html
    assert "raiseSelectionTracksUi" in ts
    assert "lowerSelectionTracksUi" in ts
    assert "renameSelectionTracksUi" in ts
