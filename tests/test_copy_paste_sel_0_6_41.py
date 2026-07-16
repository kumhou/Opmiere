"""copy_selection + paste_selection + clipboard status (0.6.41)."""

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


def test_copy_paste_selection():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cps_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 15, 0, 10)

        st0 = ed.selection_clipboard_status()
        assert st0["has_selection_clipboard"] is False

        cp = ed.copy_selection([c1.id, c2.id])
        assert cp["count"] == 2
        assert cp["span_frames"] == 25  # 0..25 (15+10)
        assert ed.selection_clipboard_status()["selection_count"] == 2

        n_before = len(ed.project.track_by_id(tr.id).clips)
        pst = ed.paste_selection(start=40, prefer_source_tracks=True)
        assert pst["count"] == 2
        assert pst["error_count"] == 0
        n_after = len(ed.project.track_by_id(tr.id).clips)
        assert n_after == n_before + 2
        starts = sorted(int(c.start) for c in ed.project.track_by_id(tr.id).clips)
        assert 40 in starts
        assert 55 in starts  # 40 + 15 rel
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_41():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/copy_selection" in app
    assert "/api/edit/paste_selection" in app
    assert "/api/edit/selection_clipboard_status" in app
    assert "def copy_selection" in mcp
    assert "def paste_selection" in mcp
    assert "def selection_clipboard_status" in mcp
    assert 'id="btn-copy-sel"' in html
    assert 'id="btn-paste-sel"' in html
    assert 'id="btn-clip-status"' in html
    assert "copySelectionUi" in ts
    assert "pasteSelectionAtPlayheadUi" in ts
    assert "selectionClipboardStatusUi" in ts
