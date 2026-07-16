"""split_selection_evenly + markers_at_selection_mids + edge fades (0.6.13)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_even_split_mids_fades():
    root = Path(tempfile.mkdtemp(prefix="opmiere_emf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.8)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        assert c.timeline_duration_frames >= 4
        sp = ed.split_selection_evenly([c.id], parts=2)
        assert sp["count"] == 1
        pieces = sp["splits"][0]["piece_ids"]
        assert len(pieces) >= 2
        vids = sum(1 for t in ed.project.tracks for _ in t.clips if t.kind == "video")
        assert vids >= 2

        mids = ed.markers_at_selection_mids(pieces[:2])
        assert mids["count"] == 2

        fd = ed.apply_edge_fades_to_selection(
            pieces[:1], fade_in_frames=3, fade_out_frames=3,
        )
        assert fd.get("count", 0) >= 1 or "clips" in fd
        clip = ed._find_clip(pieces[0])
        assert any(e.get("type") == "fade" for e in (clip.effects or []))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_13():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/split_selection_evenly" in app
    assert "/api/markers/selection_mids" in app
    assert "/api/edit/edge_fades_selection" in app
    assert "def split_selection_evenly" in mcp
    assert "def markers_at_selection_mids" in mcp
    assert "def apply_edge_fades_to_selection" in mcp
    assert 'id="btn-split-even"' in html
    assert 'id="btn-mkr-mid"' in html
    assert 'id="btn-fade-sel"' in html
    assert "splitSelectionEvenlyUi" in ts
    assert "markersSelectionMidsUi" in ts
    assert "edgeFadesSelectionUi" in ts
