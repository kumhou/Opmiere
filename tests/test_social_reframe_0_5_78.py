"""export_to_size / export_social_pack / reframe_clip (0.5.78)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=320x180:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_reframe_clip_9_16():
    root = Path(tempfile.mkdtemp(prefix="opmiere_reframe_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        r = ed.reframe_clip(c.id, "9:16", anchor="center")
        assert r["crop_box"]["height"] == 180
        # 9:16 of height 180 → width 101 or 100 even
        assert r["crop_box"]["width"] < 320
        assert any(e.get("type") == "crop" for e in (c.effects or []))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_to_size_and_social_pack():
    root = Path(tempfile.mkdtemp(prefix="opmiere_social_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.35)
        ed = Editor.create(root / "p.opm", fps=10, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        one = root / "vert.mp4"
        r = ed.export_to_size(one, 180, 320, fit="cover")
        assert Path(r["path"]).is_file()
        assert r["width"] == 180
        assert r["height"] == 320
        pack = root / "pack"
        # use tiny custom via export_to_size only — social pack does 3 full exports
        # keep pack to one small variant by calling export_to_size thrice under pack
        # exercise social_pack with square only for speed
        sp = ed.export_social_pack(pack, variants=["square"], name_prefix="t")
        assert sp["count"] == 1
        assert Path(sp["written"][0]["path"]).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_78():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/to_size" in app
    assert "/api/export/social_pack" in app
    assert "/api/clip/reframe" in app
    assert "def export_social_pack" in mcp
    assert "def reframe_clip" in mcp
    assert 'id="btn-social"' in html
    assert "exportSocialPackUi" in ts
