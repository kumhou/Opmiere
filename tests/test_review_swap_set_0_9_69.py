"""review_selection_set + swap_selection_set_pair (0.9.69)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
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


def test_review_and_swap_pair_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_revswap_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 20, duration_frames=12)
        ed.save_selection_set("hero", [c1.id, c2.id])

        rev = ed.review_selection_set("hero")
        assert rev.get("selection_set") == "hero"
        assert rev.get("clip_count") == 2

        s1, e1 = int(ed._find_clip(c1.id).start), int(ed._find_clip(c2.id).start)
        sw = ed.swap_selection_set_pair("hero")
        assert sw.get("selection_set") == "hero"
        assert sw.get("clip_id_a")
        assert sw.get("clip_id_b")
        s1b, e1b = int(ed._find_clip(c1.id).start), int(ed._find_clip(c2.id).start)
        assert {s1b, e1b} == {s1, e1}
        assert s1b != s1 or e1b != e1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_69():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/review_selection_set" in app
    assert "/api/edit/swap_selection_set_pair" in app
    assert "def review_selection_set" in mcp
    assert "def swap_selection_set_pair" in mcp
    assert 'id="btn-review-set2"' in html
    assert 'id="btn-swap-pair-set"' in html
    assert "reviewSelectionSetUi" in ts
    assert "swapSelectionSetPairUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "review_selection_set" in cat["tool_ids"]
    assert "swap_selection_set_pair" in cat["tool_ids"]
