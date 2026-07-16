"""OpenShot plan adapter depth + desktop context menu wiring (0.4.58)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import build_openshot_plan, clip_visual_props


def _vid(path: Path, color: str = "purple", d: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_clip_visual_props_and_plan_mapping():
    root = Path(tempfile.mkdtemp(prefix="opmiere_098_"))
    try:
        base = root / "base.mp4"
        ov = root / "ov.mp4"
        _vid(base, "green", 0.8)
        _vid(ov, "yellow", 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        t0 = ed.add_track("video")
        t1 = ed.add_track("video")
        c0 = ed.place_from_file(base, "video", t0.id, 0)
        c1 = ed.place_from_file(ov, "video", t1.id, 0)
        ed.set_position(c1.id, x=0.1, y=0.1, scale=0.4)
        ed.set_clip_opacity(c1.id, 0.7)
        ed.apply_effect(c1.id, {"type": "rotate", "degrees": 15})
        ed.apply_effect(c1.id, {"type": "vignette", "strength": 0.4})

        vis = clip_visual_props(ed.project.tracks[1].clips[0])
        assert abs(vis["opacity"] - 0.7) < 1e-6
        assert abs(vis["rotation"] - 15) < 1e-6
        assert "opacity" in vis["mapped_effects"]
        assert "rotate" in vis["mapped_effects"]
        # v5+: vignette is mapped for path-C (was unmapped in early adapter)
        assert "vignette" in vis["mapped_effects"]

        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 2
        assert "opacity" in plan.get("mapped", [])
        assert "rotate" in plan.get("mapped", [])
        assert "transform" in plan.get("mapped", [])
        assert "vignette" in plan.get("mapped", [])
        overlay = next(c for c in plan["clips"] if c["layer"] == 2)
        assert abs(float(overlay["opacity"]) - 0.7) < 1e-6
        assert abs(float(overlay["rotation"]) - 15) < 1e-6
        assert "transform" in overlay
        assert float(overlay.get("vignette") or 0) > 0
        assert c0.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_adapter_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "openClipMenu" in ts
    assert "runClipMenuAction" in ts
    assert "adapter_version" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="clip-menu"' in html
    assert "API dogfood" in html
    assert "Product shell" in html
