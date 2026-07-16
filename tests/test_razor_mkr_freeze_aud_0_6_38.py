"""razor_selection_at_markers + freeze_selection_at + export audio default (0.6.38)."""

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
            "-f", "lavfi", "-i", f"color=c=orange:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_razor_mkr_freeze_aud():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rfa_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 40)

        ed.project.add_marker(frame=10, label="A")
        ed.project.add_marker(frame=25, label="B")
        rz = ed.razor_selection_at_markers([c1.id])
        assert rz["count"] == 2
        assert len(ed.project.track_by_id(tr.id).clips) == 3

        pieces = ed.project.track_by_id(tr.id).clips_in_order()
        aud = ed.export_selection_audio_default(
            [pieces[0].id],
            filename="sel.wav",
        )
        path = Path(aud.get("path") or aud.get("output_path") or "")
        assert path.is_file() or (ed.bundle.root / "exports" / "sel.wav").is_file()

        # freeze after export (freeze still may land on overlay / same track)
        first = pieces[0]
        fr = ed.freeze_selection_at([first.id], int(first.start) + 2, duration_frames=10)
        assert fr["count"] == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_38():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/razor_selection_at_markers" in app
    assert "/api/edit/freeze_selection_at" in app
    assert "/api/edit/export_selection_audio_default" in app
    assert "def razor_selection_at_markers" in mcp
    assert "def freeze_selection_at" in mcp
    assert "def export_selection_audio_default" in mcp
    assert 'id="btn-razor-mkr-sel"' in html
    assert 'id="btn-freeze-ph-sel"' in html
    assert 'id="btn-aud-sel"' in html
    assert "razorSelectionAtMarkersUi" in ts
    assert "freezeSelectionAtPlayheadUi" in ts
    assert "exportSelectionAudioDefaultUi" in ts
