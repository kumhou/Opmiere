"""extract_selection + join_selection + set_selection_position (0.6.23)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_extract_join_pip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ejp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)  # ~60f
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 10, 10, 20)

        j = ed.join_selection([c1.id, c2.id])
        assert j["count"] == 1
        assert ed._find_clip(c1.id).src_out == 20
        remaining = [c.id for c in ed.project.track_by_id(tr.id).clips]
        assert c2.id not in remaining

        c3 = ed.add_clip(tr.id, med.id, int(ed._find_clip(c1.id).end) + 5, 0, 8)
        pos = ed.set_selection_position([c1.id, c3.id], 1.0, 1.0, 0.35)
        assert pos["count"] == 2
        assert ed._find_clip(c1.id).position["scale"] == 0.35

        # extract c3 leaves c1 and closes gap after c3 only (ripple on that hole)
        before_end = ed._find_clip(c1.id).end
        ex = ed.extract_selection([c3.id])
        assert ex["count"] == 1
        rem = [c.id for c in ed.project.track_by_id(tr.id).clips]
        assert c3.id not in rem
        assert c1.id in rem
        assert ed._find_clip(c1.id).end == before_end
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_23():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/extract_selection" in app
    assert "/api/edit/join_selection" in app
    assert "/api/edit/selection_position" in app
    assert "def extract_selection" in mcp
    assert "def join_selection" in mcp
    assert "def set_selection_position" in mcp
    assert 'id="btn-extract-sel"' in html
    assert 'id="btn-join-sel"' in html
    assert 'id="btn-pip-sel"' in html
    assert "extractSelectionUi" in ts
    assert "joinSelectionUi" in ts
    assert "pipSelectionUi" in ts
