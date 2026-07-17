"""selection_media_health + apply_lut_selection (0.6.81)."""

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
            "-f", "lavfi", "-i", f"color=c=brown:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=520:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def _tiny_cube(path: Path) -> None:
    path.write_text(
        "TITLE \"Identity\"\n"
        "LUT_3D_SIZE 2\n"
        "0 0 0\n1 0 0\n0 1 0\n1 1 0\n"
        "0 0 1\n1 0 1\n0 1 1\n1 1 1\n",
        encoding="utf-8",
    )


def test_media_health_and_lut():
    root = Path(tempfile.mkdtemp(prefix="opmiere_hl_"))
    try:
        v = root / "v.mp4"
        cube = root / "id.cube"
        _vid(v)
        _tiny_cube(cube)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        h = ed.selection_media_health([c.id])
        assert h.get("ok") is True
        assert int(h.get("offline_count") or 0) == 0
        assert int(h.get("clip_count") or 0) == 1
        assert "durations" in h
        assert "path_c" in h

        lut = ed.apply_lut_selection([c.id], str(cube))
        assert int(lut.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "lut3d" in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_81():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_media_health" in app
    assert "/api/edit/apply_lut_selection" in app
    assert "def selection_media_health" in mcp
    assert "def apply_lut_selection" in mcp
    assert 'id="btn-health-sel"' in html
    assert 'id="btn-lut-sel"' in html
    assert "selectionMediaHealthUi" in ts
    assert "applyLutSelectionUi" in ts
