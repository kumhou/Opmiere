"""OpenShot adapter v6: film_grain + chroma_key + per-clip path-C support."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import (
    ADAPTER_VERSION,
    build_openshot_plan,
    clip_path_c_support,
    clip_visual_props,
    path_c_effect_catalog,
)


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=green:s=160x90:d=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_adapter_v6_grain_chroma():
    root = Path(tempfile.mkdtemp(prefix="opmiere_v6_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "film_grain", "amount": 22})
        ed.apply_effect(
            c.id,
            {"type": "chroma_key", "color": "green", "similarity": 0.2, "blend": 0.08},
        )
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "film_grain" in vis["mapped_effects"]
        assert "chroma_key" in vis["mapped_effects"]
        assert vis["film_grain"] == 22
        assert vis["chroma_key"]["color"] == "green"

        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 6
        assert int(plan.get("adapter_version") or 0) >= ADAPTER_VERSION
        clip0 = plan["clips"][0]
        assert clip0.get("film_grain", 0) == 22
        assert clip0.get("chroma_key", {}).get("color") == "green"
        assert "film_grain" in plan.get("mapped", [])
        assert "chroma_key" in plan.get("mapped", [])

        support = clip_path_c_support(ed.project.tracks[0].clips[0])
        assert support["path_c_ready"] is True
        assert "film_grain" in support["mapped"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_catalog_v6():
    cat = path_c_effect_catalog()
    assert int(cat.get("adapter_version") or 0) >= 6
    assert "film_grain" in cat["mapped"]
    assert "chroma_key" in cat["mapped"]
    assert "curves" in cat["unmapped"]
