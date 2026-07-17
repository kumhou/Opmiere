"""extend_selection_set_to_next + reverse_selection_set_order (0.9.65)."""

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


def test_extend_and_reverse_order_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_extrev_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        # two clips with a gap; first has spare source to extend
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 20, duration_frames=10)
        ed.save_selection_set("hero", [c1.id, c2.id])

        rev = ed.reverse_selection_set_order("hero")
        assert rev.get("selection_set") == "hero"
        assert int(rev.get("count") or 0) >= 1

        # re-save after reverse (clip starts changed; ids same)
        ed.save_selection_set("hero", [c1.id, c2.id])
        ext = ed.extend_selection_set_to_next("hero")
        assert ext.get("selection_set") == "hero"
        assert "count" in ext
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_65():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/extend_selection_set_to_next" in app
    assert "/api/edit/reverse_selection_set_order" in app
    assert "def extend_selection_set_to_next" in mcp
    assert "def reverse_selection_set_order" in mcp
    assert 'id="btn-ext-next-set"' in html
    assert 'id="btn-rev-order-set"' in html
    assert "extendSelectionSetToNextUi" in ts
    assert "reverseSelectionSetOrderUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "extend_selection_set_to_next" in cat["tool_ids"]
    assert "reverse_selection_set_order" in cat["tool_ids"]
