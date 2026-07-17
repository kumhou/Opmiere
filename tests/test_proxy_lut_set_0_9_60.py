"""ensure_selection_set_proxies + clear_selection_set_luts (0.9.60)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
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


def test_proxies_and_clear_luts_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_proxylut_"))
    try:
        v = root / "v.mp4"
        cube = root / "id.cube"
        _vid(v, 0.5)
        _tiny_cube(cube)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])
        ed.apply_lut_selection_set("hero", str(cube), replace=True)

        px = ed.ensure_selection_set_proxies("hero", height=360, force=False)
        assert px.get("selection_set") == "hero"
        assert "ensured_count" in px or "media_count" in px

        clr = ed.clear_selection_set_luts("hero")
        assert clr.get("selection_set") == "hero"
        assert int(clr.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "lut3d" not in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_60():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/ensure_selection_set_proxies" in app
    assert "/api/edit/clear_selection_set_luts" in app
    assert "def ensure_selection_set_proxies" in mcp
    assert "def clear_selection_set_luts" in mcp
    assert 'id="btn-proxy-set"' in html
    assert 'id="btn-clr-lut-set"' in html
    assert "ensureSelectionSetProxiesUi" in ts
    assert "clearSelectionSetLutsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "ensure_selection_set_proxies" in cat["tool_ids"]
    assert "clear_selection_set_luts" in cat["tool_ids"]
