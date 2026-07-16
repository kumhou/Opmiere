"""OpenShot adapter v5: vignette / sharpen / ken_burns / white_balance."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import (
    ADAPTER_VERSION,
    build_openshot_plan,
    clip_visual_props,
    path_c_effect_catalog,
)


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=olive:s=160x90:d=0.8",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_adapter_v5_grade_motion_mapping():
    root = Path(tempfile.mkdtemp(prefix="opmiere_v5_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "vignette", "strength": 1.2})
        ed.apply_effect(c.id, {"type": "sharpen", "amount": 1.5})
        ed.apply_effect(
            c.id,
            {
                "type": "ken_burns",
                "zoom_start": 1.0,
                "zoom_end": 1.4,
                "x_start": 0.4,
                "y_start": 0.5,
                "x_end": 0.6,
                "y_end": 0.5,
            },
        )
        ed.apply_effect(
            c.id, {"type": "white_balance", "temperature": 4800, "mix": 0.8}
        )
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        for kind in ("vignette", "sharpen", "ken_burns", "white_balance"):
            assert kind in vis["mapped_effects"]
        assert vis["vignette"] > 0
        assert vis["sharpen"] > 0
        assert vis["ken_burns"] is not None
        assert vis["ken_burns"]["zoom_end"] == 1.4
        assert vis["white_balance"] is not None
        assert vis["white_balance"]["warmth"] < 0  # cooler than 6500

        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 5
        assert int(plan.get("adapter_version") or 0) >= ADAPTER_VERSION
        clip0 = plan["clips"][0]
        assert clip0.get("vignette", 0) > 0
        assert clip0.get("sharpen", 0) > 0
        assert clip0.get("ken_burns", {}).get("zoom_end") == 1.4
        assert "warmth" in (clip0.get("white_balance") or {})
        for kind in ("vignette", "sharpen", "ken_burns", "white_balance"):
            assert kind in plan.get("mapped", [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_effect_catalog():
    cat = path_c_effect_catalog()
    assert int(cat.get("adapter_version") or 0) >= 5
    assert "vignette" in cat["mapped"]
    # Catalog always exposes adapter version + mapped vocabulary
    assert int(cat.get("adapter_version") or 0) >= 5
    assert "opacity" in cat["mapped"]
