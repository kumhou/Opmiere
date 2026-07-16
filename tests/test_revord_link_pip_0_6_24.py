"""clear_selection_position + reverse_selection_order + link/unlink (0.6.24)."""

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
            "-f", "lavfi", "-i", f"color=c=maroon:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_revord_link_clear_pip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rlp_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 15, 0, 10)
        c3 = ed.add_clip(tr.id, med.id, 30, 0, 10)

        ed.set_selection_position([c1.id], 0.5, 0.5, 0.4)
        assert ed._find_clip(c1.id).position is not None
        clr = ed.clear_selection_position([c1.id])
        assert clr["count"] == 1
        assert ed._find_clip(c1.id).position is None

        rev = ed.reverse_selection_order([c1.id, c2.id, c3.id])
        assert rev["count"] >= 2
        assert ed._find_clip(c1.id).start == 30
        assert ed._find_clip(c3.id).start == 0

        ln = ed.link_selection([c1.id, c2.id])
        assert ln["count"] == 2
        assert ed._find_clip(c1.id).link_group == ed._find_clip(c2.id).link_group
        un = ed.unlink_selection([c1.id, c2.id])
        assert un.get("count", 0) >= 1 or "cleared" in un or "clip_ids" in un
        assert ed._find_clip(c1.id).link_group is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_24():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/clear_selection_position" in app
    assert "/api/edit/reverse_selection_order" in app
    assert "/api/edit/link_selection" in app
    assert "/api/edit/unlink_selection" in app
    assert "def clear_selection_position" in mcp
    assert "def reverse_selection_order" in mcp
    assert "def link_selection" in mcp
    assert "def unlink_selection" in mcp
    assert 'id="btn-clear-pip-sel"' in html
    assert 'id="btn-rev-ord-sel"' in html
    assert 'id="btn-link-sel"' in html
    assert 'id="btn-unlink-sel"' in html
    assert "clearPipSelectionUi" in ts
    assert "reverseSelectionOrderUi" in ts
    assert "linkSelectionUi" in ts
    assert "unlinkSelectionUi" in ts
