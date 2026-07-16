"""OpenShot adapter v3: speed remap, crop, desktop comfy/tc (0.4.59)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import build_openshot_plan, clip_visual_props


def _vid(path: Path, color: str = "teal", d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_speed_crop_plan_mapping():
    root = Path(tempfile.mkdtemp(prefix="opmiere_099_"))
    try:
        v = root / "v.mp4"
        _vid(v, "teal", 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.set_speed(c.id, 2.0)
        ed.set_clip_crop(c.id, 160, 90, x="center", y="center")

        vis = clip_visual_props(
            ed.project.tracks[0].clips[0],
            project_w=320,
            project_h=180,
        )
        assert "crop" in vis["mapped_effects"]
        assert vis["crop"] is not None

        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert plan.get("adapter_version") == 3
        assert "speed" in plan.get("mapped", [])
        assert "crop" in plan.get("mapped", [])
        # speed is mapped, not listed as unsupported summary kind
        assert "speed" not in plan.get("unsupported", [])
        clip = plan["clips"][0]
        assert abs(float(clip["speed"]) - 2.0) < 1e-6
        assert clip.get("time_remap", {}).get("enabled") is True
        assert "crop" in clip
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_fallback_speed_math():
    from opmiere.render.openshot_runtime import _active_clip_at

    plan = {
        "clips": [
            {
                "id": "a",
                "path": "/x.mp4",
                "position": 0.0,
                "start": 0.0,
                "end": 2.0,
                "layer": 1,
                "speed": 2.0,
                "timeline_duration": 1.0,
                "time_remap": {
                    "enabled": True,
                    "source_start": 0.0,
                    "source_end": 2.0,
                    "timeline_duration": 1.0,
                    "speed": 2.0,
                },
            }
        ]
    }
    active = _active_clip_at(plan, 0.5)
    assert active is not None
    assert active["id"] == "a"
    # local 0.5s * speed 2 = 1.0s into source
    local = 0.5 - float(active["position"])
    src = float(active["time_remap"]["source_start"]) + local * float(
        active["time_remap"]["speed"]
    )
    assert abs(src - 1.0) < 1e-6


def test_v3_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "pill-comfy" in ts or "check_comfy=true" in ts
    assert "tc-tick" in ts
    assert 'data-act="match"' in (
        root / "ui-desktop" / "index.html"
    ).read_text(encoding="utf-8") or "matchFrameAtPlayhead" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="pill-comfy"' in html
    assert 'data-act="match"' in html
