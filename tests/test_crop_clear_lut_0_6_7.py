"""paste_crop + clear_effects + apply_lut_to_clips (0.6.7)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _minimal_cube(path: Path) -> None:
    # Identity 2-point 1D LUT in .cube form (accepted by validation as path exists)
    path.write_text(
        "TITLE \"identity\"\n"
        "LUT_3D_SIZE 2\n"
        "0.0 0.0 0.0\n"
        "1.0 0.0 0.0\n"
        "0.0 1.0 0.0\n"
        "1.0 1.0 0.0\n"
        "0.0 0.0 1.0\n"
        "1.0 0.0 1.0\n"
        "0.0 1.0 1.0\n"
        "1.0 1.0 1.0\n",
        encoding="utf-8",
    )


def test_paste_crop_clear_lut():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pcl_"))
    try:
        v = root / "v.mp4"
        lut = root / "id.cube"
        _vid(v)
        _minimal_cube(lut)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end))
        ed.apply_effect(c1.id, {"type": "crop", "width": 80, "height": 90, "x": 0, "y": 0})
        ed.apply_vignette(c1.id, strength=0.3)
        pc = ed.paste_crop(c1.id, [c2.id])
        assert pc["count"] == 1
        assert any(
            e.get("type") == "crop" and int(e.get("width", 0)) == 80
            for e in (ed._find_clip(c2.id).effects or [])
        )
        cl = ed.clear_effects([c2.id], types=["crop"])
        assert cl["count"] == 1
        assert not any(
            e.get("type") == "crop" for e in (ed._find_clip(c2.id).effects or [])
        )
        # vignette still on c1
        assert any(
            e.get("type") == "vignette" for e in (ed._find_clip(c1.id).effects or [])
        )
        lut_r = ed.apply_lut_to_clips([c1.id, c2.id], str(lut))
        assert lut_r["count"] == 2
        for cid in (c1.id, c2.id):
            assert any(
                e.get("type") == "lut3d" for e in (ed._find_clip(cid).effects or [])
            )
        ed.clear_effects([c1.id, c2.id])
        assert not (ed._find_clip(c1.id).effects or [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_7():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/paste_crop" in app
    assert "/api/clip/clear_effects" in app
    assert "/api/clip/apply_lut" in app
    assert "def paste_crop" in mcp
    assert "def clear_effects" in mcp
    assert "def apply_lut_to_clips" in mcp
    assert 'id="btn-paste-crop"' in html
    assert 'id="btn-clr-fx"' in html
    assert "pasteCropUi" in ts
    assert "clearEffectsUi" in ts
