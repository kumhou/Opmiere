"""stagger_selection_set + match_selection_duration_set (0.9.42)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_stagger_and_match_duration_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 12, duration_frames=18)
        ed.save_selection_set("hero", [c1.id, c2.id])

        stag = ed.stagger_selection_set("hero", 6)
        assert stag.get("selection_set") == "hero"
        assert stag.get("count", 0) >= 1
        assert int(ed._find_clip(c2.id).start) == 12 + 6

        matched = ed.match_selection_duration_set(
            "hero", target_frames=12,
        )
        assert matched.get("selection_set") == "hero"
        assert matched.get("target_frames") == 12
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_42():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/stagger_selection_set" in app
    assert "/api/edit/match_selection_duration_set" in app
    assert "def stagger_selection_set" in mcp
    assert "def match_selection_duration_set" in mcp
    assert 'id="btn-stagger-set"' in html
    assert 'id="btn-match-dur-set"' in html
    assert "staggerSelectionSetUi" in ts
    assert "matchSelectionDurationSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "stagger_selection_set" in cat["tool_ids"]
    assert "match_selection_duration_set" in cat["tool_ids"]
