"""fill_selection_set_gaps + retarget_selection_set_media (0.9.66)."""

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


def test_fill_gaps_and_retarget_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fillrt_"))
    try:
        v1 = root / "a.mp4"
        v2 = root / "b.mp4"
        _vid(v1, 0.5, "blue")
        _vid(v2, 0.5, "red")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v1, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v1, "video", tr.id, 20, duration_frames=12)
        m2 = ed.import_media(v2, "video")
        ed.save_selection_set("hero", [c1.id, c2.id])

        fill = ed.fill_selection_set_gaps("hero", mode="close")
        assert fill.get("selection_set") == "hero"
        assert fill.get("mode") == "close"

        rt = ed.retarget_selection_set_media(
            "hero", m2.id, keep_source_range=True,
        )
        assert rt.get("selection_set") == "hero"
        assert rt.get("media_id") == m2.id
        assert int(rt.get("count") or 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_66():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/fill_selection_set_gaps" in app
    assert "/api/edit/retarget_selection_set_media" in app
    assert "def fill_selection_set_gaps" in mcp
    assert "def retarget_selection_set_media" in mcp
    assert 'id="btn-fill-gaps-set"' in html
    assert 'id="btn-retarget-set"' in html
    assert "fillSelectionSetGapsUi" in ts
    assert "retargetSelectionSetMediaUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "fill_selection_set_gaps" in cat["tool_ids"]
    assert "retarget_selection_set_media" in cat["tool_ids"]
