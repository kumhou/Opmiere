"""set_selection_set_gain + set_selection_set_meta (0.9.15)."""

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


def test_gain_and_meta_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_gms_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        gain = ed.set_selection_set_gain("hero", -3.0)
        assert gain.get("selection_set") == "hero"
        assert gain.get("db") == -3.0
        levels = ed.selection_set_levels_report("hero")
        assert levels.get("non_default_count", 0) >= 1

        meta = ed.set_selection_set_meta(
            "hero", clip_name="shot_a", color="red",
        )
        assert meta.get("selection_set") == "hero"
        mr = ed.selection_set_meta_report("hero")
        assert mr.get("named_count", 0) >= 1
        assert mr.get("colored_count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_15():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/set_selection_set_gain" in app
    assert "/api/edit/set_selection_set_meta" in app
    assert "def set_selection_set_gain" in mcp
    assert "def set_selection_set_meta" in mcp
    assert 'id="btn-gain-set"' in html
    assert 'id="btn-meta-set"' in html
    assert "setSelectionSetGainUi" in ts
    assert "setSelectionSetMetaUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "set_selection_set_gain" in cat["tool_ids"]
    assert "set_selection_set_meta" in cat["tool_ids"]
