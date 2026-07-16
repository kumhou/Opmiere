"""hflip/vflip effects + path-C adapter v20 (0.5.69)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.model import KNOWN_EFFECT_TYPES
from opmiere.render.openshot_map import (
    ADAPTER_VERSION,
    build_openshot_plan,
    clip_visual_props,
    path_c_effect_catalog,
)


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_set_clip_flip_and_path_c():
    assert "hflip" in KNOWN_EFFECT_TYPES
    assert "vflip" in KNOWN_EFFECT_TYPES
    assert int(ADAPTER_VERSION) >= 20
    cat = path_c_effect_catalog()
    assert int(cat.get("adapter_version") or 0) >= 20
    assert "hflip" in cat["mapped"]
    assert "vflip" in cat["mapped"]

    root = Path(tempfile.mkdtemp(prefix="opmiere_flip_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        r = ed.set_clip_flip(c.id, horizontal=True, vertical=False)
        assert r["hflip"]["to"] is True
        types = {e.get("type") for e in c.effects}
        assert "hflip" in types
        vis = clip_visual_props(c)
        assert vis["flip_h"] is True
        assert "hflip" in vis["mapped_effects"]
        assert "hflip" not in vis["unmapped_effects"]
        plan = build_openshot_plan(ed.project, ed.bundle)
        assert int(plan.get("adapter_version") or 0) >= 20
        clips = plan.get("clips") or []
        assert clips and clips[0].get("flip_h") is True
        # toggle off
        r2 = ed.set_clip_flip(c.id, toggle_h=True)
        assert r2["hflip"]["to"] is False
        assert not any(e.get("type") == "hflip" for e in c.effects)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_69():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/flip" in app
    assert "def set_clip_flip" in mcp
    assert 'id="btn-fliph"' in html
    assert "flipSelection" in ts
