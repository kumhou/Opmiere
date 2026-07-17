"""export_selection_clips_pack + clear_selection_luts (0.6.77)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=green:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=480:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_clips_pack_and_clear_luts():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cp_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)

        # inject lut3d effect without real cube file (type only for clear test)
        with ed._mutate():
            clip = ed._find_clip(c.id)
            clip.effects = list(clip.effects or []) + [
                {"type": "lut3d", "path": str(root / "fake.cube")},
            ]
        clr = ed.clear_selection_luts([c.id])
        assert int(clr.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "lut3d" not in types

        pack = ed.export_selection_clips_pack([c.id], prefix="sel")
        assert int(pack.get("count") or 0) >= 1
        assert pack.get("ok") is True
        out = Path(pack.get("output_dir") or "")
        assert out.is_dir()
        mp4s = list(out.glob("*.mp4"))
        assert len(mp4s) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_77():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_clips_pack" in app
    assert "/api/edit/clear_selection_luts" in app
    assert "def export_selection_clips_pack" in mcp
    assert "def clear_selection_luts" in mcp
    assert 'id="btn-clips-pack-sel"' in html
    assert 'id="btn-lut-clr-sel"' in html
    assert "exportSelectionClipsPackUi" in ts
    assert "clearSelectionLutsUi" in ts
