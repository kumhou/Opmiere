"""selection_to_new_track + duplicate_selection_to_track (0.6.17)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_selection_new_and_dup_track():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ndt_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end))
        n_tracks = len(ed.project.tracks)
        r = ed.selection_to_new_track([c2.id], name="Lifted")
        assert r["count"] == 1
        assert r["new_track_id"]
        assert len(ed.project.tracks) == n_tracks + 1
        assert ed.project.track_by_id(r["new_track_id"]).name == "Lifted"
        assert c2.id in {
            c.id for c in ed.project.track_by_id(r["new_track_id"]).clips
        }

        # dup c1 onto that overlay track
        d = ed.duplicate_selection_to_track(
            [c1.id], r["new_track_id"], preserve_starts=True,
        )
        assert d["count"] == 1
        assert d["clips"][0]["clip_id"] != c1.id
        over = ed.project.track_by_id(r["new_track_id"])
        assert len(over.clips) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_17():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_to_new_track" in app
    assert "/api/edit/duplicate_selection_to_track" in app
    assert "def selection_to_new_track" in mcp
    assert "def duplicate_selection_to_track" in mcp
    assert 'id="btn-new-trk"' in html
    assert 'id="btn-dup-trk"' in html
    assert "selectionToNewTrackUi" in ts
    assert "duplicateSelectionToNewTrackUi" in ts
