"""add_transitions_to_selection + remove + stagger_selection (0.6.12)."""

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
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_xfade_hard_stagger():
    root = Path(tempfile.mkdtemp(prefix="opmiere_xst_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.2)  # ~36f @30fps
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=15)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end), duration_frames=15)
        c3 = ed.place_from_file(v, "video", tr.id, int(c2.end), duration_frames=15)
        ids = [c1.id, c2.id, c3.id]
        xf = ed.add_transitions_to_selection(
            ids, transition_type="cross_dissolve", duration_frames=6,
        )
        assert xf["count"] >= 1
        assert ed._find_clip(c2.id).transition_in is not None

        hard = ed.remove_transitions_from_selection(ids)
        assert hard["count"] >= 1
        assert ed._find_clip(c2.id).transition_in is None

        # re-place clean for stagger on overlay freeform
        over = ed.add_track("video")
        a = ed.place_from_file(v, "video", over.id, 0, duration_frames=8)
        b = ed.place_from_file(v, "video", over.id, 0, duration_frames=8)
        c = ed.place_from_file(v, "video", over.id, 0, duration_frames=8)
        st = ed.stagger_selection([a.id, b.id, c.id], offset_frames=5)
        assert st["count"] == 2
        starts = sorted(
            ed._find_clip(x).start for x in (a.id, b.id, c.id)
        )
        assert starts[1] - starts[0] == 5
        assert starts[2] - starts[0] == 10
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_12():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/transitions_selection" in app
    assert "/api/edit/remove_transitions_selection" in app
    assert "/api/edit/stagger_selection" in app
    assert "def add_transitions_to_selection" in mcp
    assert "def remove_transitions_from_selection" in mcp
    assert "def stagger_selection" in mcp
    assert 'id="btn-xfade-sel"' in html
    assert 'id="btn-hard-sel"' in html
    assert 'id="btn-stagger"' in html
    assert "transitionsSelectionUi" in ts
    assert "removeTransitionsSelectionUi" in ts
    assert "staggerSelectionUi" in ts
