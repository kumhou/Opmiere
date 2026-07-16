"""OpenShot adapter v4: blur/color/fade mapping."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import build_openshot_plan, clip_visual_props


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_adapter_v4_blur_color_fade():
    root = Path(tempfile.mkdtemp(prefix="opmiere_104_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "blur", "amount": 2.5})
        ed.apply_effect(
            c.id,
            {"type": "color", "brightness": 0.1, "contrast": 1.0, "saturation": 1.0},
        )
        ed.apply_effect(
            c.id, {"type": "fade", "direction": "in", "duration_frames": 6}
        )
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "blur" in vis["mapped_effects"]
        assert "color" in vis["mapped_effects"]
        assert "fade" in vis["mapped_effects"]
        assert vis["blur"] > 0
        assert vis["fade_in_frames"] == 6
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        # Current contract floor; allow future adapter major bumps without CI pin-rot.
        assert int(plan.get("adapter_version") or 0) >= 4
        assert plan["clips"][0].get("blur", 0) > 0
        assert plan["clips"][0].get("fade_in_frames") == 6
    finally:
        shutil.rmtree(root, ignore_errors=True)
