"""Wiring for 0.5.41 path-C glow mapping (no package-version pin)."""

from pathlib import Path
import shutil
import subprocess
import tempfile

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=maroon:s=160x90:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_ship_0_5_41_glow():
    assert int(ADAPTER_VERSION) >= 8
    root = Path(tempfile.mkdtemp(prefix="opmiere_glow_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "glow", "amount": 10, "intensity": 0.55})
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "glow" in vis["mapped_effects"]
        assert vis["glow"]["amount"] == 10
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 8
        assert plan["clips"][0].get("glow", {}).get("intensity") == 0.55
        assert "glow" in plan.get("mapped", [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_0_5_41_desktop_glow_preset():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert 'type: "glow"' in ts or "type: 'glow'" in ts
