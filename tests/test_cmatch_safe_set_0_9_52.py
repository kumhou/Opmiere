"""color_match_selection_set + safe_area_selection_set (0.9.52)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5, color: str = "dimgray") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_color_match_and_safe_area_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cmsafe_"))
    try:
        v1 = root / "a.mp4"
        v2 = root / "b.mp4"
        _vid(v1, 0.5, "blue")
        _vid(v2, 0.5, "red")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v1, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v2, "video", tr.id, 12, duration_frames=12)
        ed.save_selection_set("hero", [c1.id, c2.id])

        cm = ed.color_match_selection_set("hero", strength=0.5)
        assert cm.get("selection_set") == "hero"
        assert cm.get("reference_clip_id")
        assert int(cm.get("matched_count") or 0) >= 1

        sa = ed.safe_area_selection_set("hero", action=0.9, title=0.8)
        assert sa.get("selection_set") == "hero"
        assert sa.get("action") == 0.9
        assert "count" in sa
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_52():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/color_match_selection_set" in app
    assert "/api/edit/safe_area_selection_set" in app
    assert "def color_match_selection_set" in mcp
    assert "def safe_area_selection_set" in mcp
    assert 'id="btn-cmatch-set"' in html
    assert 'id="btn-safe-set"' in html
    assert "colorMatchSelectionSetUi" in ts
    assert "safeAreaSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "color_match_selection_set" in cat["tool_ids"]
    assert "safe_area_selection_set" in cat["tool_ids"]
