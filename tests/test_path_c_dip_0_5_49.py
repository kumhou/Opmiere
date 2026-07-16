"""path-C adapter v12: dip_to_black/white transitions."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan


def _vid(path: Path, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d=1.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_path_c_dip_to_black():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dip_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, "navy")
        _vid(b, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, c1.end)
        ed.link_transition(c2.id, transition_type="dip_to_black", duration_frames=10)
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 12
        assert int(ADAPTER_VERSION) >= 12
        assert "transition" in plan.get("mapped", [])
        by_id = {c["id"]: c for c in plan["clips"]}
        right = by_id[c2.id]
        left = by_id[c1.id]
        assert int(right.get("fade_in_frames") or 0) >= 10
        assert int(left.get("fade_out_frames") or 0) >= 10
        assert right.get("dip_in") == "black"
        assert left.get("dip_out") == "black"
    finally:
        shutil.rmtree(root, ignore_errors=True)
