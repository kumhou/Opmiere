"""split_selection_set_at + split_selection_set_evenly (0.9.31)."""

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


def test_split_at_and_evenly_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_spset_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=20)
        ed.save_selection_set("hero", [c.id])

        at = ed.split_selection_set_at("hero", 10)
        assert at.get("selection_set") == "hero"
        assert at.get("count", 0) >= 1

        # re-save pieces for even split on first remaining long piece
        pieces = [cl for cl in tr.clips_in_order()]
        assert len(pieces) >= 2
        long = max(pieces, key=lambda x: int(x.end) - int(x.start))
        ed.save_selection_set("pieces", [long.id])
        eq = ed.split_selection_set_evenly("pieces", parts=2)
        assert eq.get("selection_set") == "pieces"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_31():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/split_selection_set_at" in app
    assert "/api/edit/split_selection_set_evenly" in app
    assert "def split_selection_set_at" in mcp
    assert "def split_selection_set_evenly" in mcp
    assert 'id="btn-split-at-set"' in html
    assert 'id="btn-split-eq-set"' in html
    assert "splitSelectionSetAtUi" in ts
    assert "splitSelectionSetEvenlyUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "split_selection_set_at" in cat["tool_ids"]
    assert "split_selection_set_evenly" in cat["tool_ids"]
