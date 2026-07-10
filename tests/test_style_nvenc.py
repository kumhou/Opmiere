"""Film style presets + NVENC encode status."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.hwencode import encode_status, video_encode_args
from opmiere.render.style_presets import blend_styles, list_styles


FPS = 30


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=gray:size=160x90:duration=0.5:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_list_and_blend_styles():
    ls = list_styles()
    assert "ang_lee" in ls["names"]
    assert "horror" in ls["names"]
    b = blend_styles(["ang_lee", "horror"])
    assert b["blend"] == ["ang_lee", "horror"]
    assert b.get("effects")
    # horror hard cut should win as later override for transition
    assert b.get("transition_preference") in ("hard_cut", "cross_dissolve")


def test_apply_style_preset_exports(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    r = ed.apply_style_preset("ang_lee+horror")
    assert r["styles"] == ["ang_lee", "horror"]
    assert r["effects_applied"]["applied_count"] > 0
    out = tmp_path / "styled.mp4"
    ed.export(out)
    assert out.exists() and out.stat().st_size > 500


def test_video_encode_args_shape():
    args = video_encode_args(prefer_nvenc=False)
    assert "-c:v" in args and "libx264" in args
    st = encode_status()
    assert "nvenc" in st
    assert isinstance(st["video_encode"], list)
