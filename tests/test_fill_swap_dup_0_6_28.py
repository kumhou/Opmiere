"""fill_selection_gaps + swap_selection_pair + duplicate_selection_block (0.6.28)."""

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
            "-f", "lavfi", "-i", f"color=c=indigo:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_fill_swap_dup_block():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fsd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 20, 0, 10)

        fill = ed.fill_selection_gaps([c1.id, c2.id], mode="slug")
        assert fill["count"] == 1
        pads = [
            c for c in ed.project.track_by_id(tr.id).clips
            if c.id not in (c1.id, c2.id)
        ]
        assert len(pads) == 1
        assert pads[0].start == 10
        assert pads[0].timeline_duration_frames == 10

        sa, sb = ed._find_clip(c1.id).start, ed._find_clip(c2.id).start
        sw = ed.swap_selection_pair(c1.id, c2.id)
        assert ed._find_clip(c1.id).start == sb
        assert ed._find_clip(c2.id).start == sa
        assert "starts" in sw

        # restore order for block dup
        ed.swap_selection_pair(c1.id, c2.id)
        end_before = max(ed._find_clip(c1.id).end, ed._find_clip(c2.id).end)
        n_before = len(ed.project.track_by_id(tr.id).clips)
        dup = ed.duplicate_selection_block([c1.id, c2.id], gap_frames=0)
        assert dup["count"] == 2
        n_after = len(ed.project.track_by_id(tr.id).clips)
        assert n_after == n_before + 2
        # earliest of block should be at previous union end
        starts = sorted(int(c.start) for c in ed.project.track_by_id(tr.id).clips)
        assert max(starts) >= end_before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_28():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/fill_selection_gaps" in app
    assert "/api/edit/swap_selection_pair" in app
    assert "/api/edit/duplicate_selection_block" in app
    assert "def fill_selection_gaps" in mcp
    assert "def swap_selection_pair" in mcp
    assert "def duplicate_selection_block" in mcp
    assert 'id="btn-fill-gaps-sel"' in html
    assert 'id="btn-swap-sel"' in html
    assert 'id="btn-dup-block-sel"' in html
    assert "fillSelectionGapsUi" in ts
    assert "swapSelectionPairUi" in ts
    assert "duplicateSelectionBlockUi" in ts
