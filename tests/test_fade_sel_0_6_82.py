"""set_selection_fades + clear_selection_fades (0.6.82)."""

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
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=530:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_selection_fades_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.6)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=15)

        r = ed.set_selection_fades(
            [c.id], fade_in_frames=4, fade_out_frames=4,
        )
        assert int(r.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "fade" in types

        clr = ed.clear_selection_fades([c.id])
        assert int(clr.get("count") or 0) >= 1
        types2 = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "fade" not in types2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_82():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/set_selection_fades" in app
    assert "/api/edit/clear_selection_fades" in app
    assert "def set_selection_fades" in mcp
    assert "def clear_selection_fades" in mcp
    assert 'id="btn-fade-sel"' in html
    assert 'id="btn-fade-clr-sel"' in html
    assert "setSelectionFadesUi" in ts
    assert "clearSelectionFadesUi" in ts
