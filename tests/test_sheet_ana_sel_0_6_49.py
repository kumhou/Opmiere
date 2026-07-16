"""make_selection_contact_sheet + analyze_selection_audio (0.6.49)."""

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
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_contact_sheet_and_analyze_audio():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sas_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        # contiguous for mix export
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end), duration_frames=6)

        sheet = ed.make_selection_contact_sheet(
            [c1.id, c2.id],
            max_tiles=12,
            tile_width=80,
            tile_height=45,
        )
        assert sheet["tile_count"] == 2
        assert Path(sheet["path"]).is_file()

        ana = ed.analyze_selection_audio([c1.id, c2.id])
        assert isinstance(ana, dict)
        assert ana.get("selection_audio_path")
        assert Path(str(ana["selection_audio_path"])).is_file()
        assert "selection_span" in ana
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_49():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/make_selection_contact_sheet" in app
    assert "/api/edit/analyze_selection_audio" in app
    assert "def make_selection_contact_sheet" in mcp
    assert "def analyze_selection_audio" in mcp
    assert 'id="btn-cs-sel"' in html
    assert 'id="btn-ana-aud-sel"' in html
    assert "makeSelectionContactSheetUi" in ts
    assert "analyzeSelectionAudioUi" in ts
