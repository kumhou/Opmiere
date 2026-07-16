"""solo/unsolo selection tracks + track states (0.6.46)."""

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
            "-f", "lavfi", "-i", f"color=c=purple:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_solo_unsolo_track_states():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sts_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr1 = ed.add_track("video")
        tr2 = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr1.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr2.id, med.id, 0, 0, 10)

        st = ed.selection_track_states([c1.id, c2.id])
        assert st["count"] == 2

        so = ed.solo_selection_tracks([c1.id], exclusive=True)
        assert so["count"] == 1
        assert ed.project.track_by_id(tr1.id).solo is True
        assert ed.project.track_by_id(tr2.id).solo is False

        ed.solo_selection_tracks([c2.id], exclusive=True)
        assert ed.project.track_by_id(tr1.id).solo is False
        assert ed.project.track_by_id(tr2.id).solo is True

        un = ed.unsolo_selection_tracks([c2.id])
        assert un["count"] == 1
        assert ed.project.track_by_id(tr2.id).solo is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_46():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/solo_selection_tracks" in app
    assert "/api/edit/unsolo_selection_tracks" in app
    assert "/api/edit/selection_track_states" in app
    assert "def solo_selection_tracks" in mcp
    assert "def unsolo_selection_tracks" in mcp
    assert "def selection_track_states" in mcp
    assert 'id="btn-solo-trk-sel"' in html
    assert 'id="btn-unsolo-trk-sel"' in html
    assert 'id="btn-trk-state-sel"' in html
    assert "soloSelectionTracksUi" in ts
    assert "unsoloSelectionTracksUi" in ts
    assert "selectionTrackStatesUi" in ts
