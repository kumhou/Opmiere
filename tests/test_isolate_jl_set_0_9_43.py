"""isolate_selection_set + selection_jl_cut_set (0.9.43)."""

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


def test_isolate_and_jl_cut_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ijl_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        keep = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        other = ed.place_from_file(v, "video", tr.id, 20, duration_frames=12)
        ed.save_selection_set("hero", [keep.id])

        iso = ed.isolate_selection_set("hero")
        assert iso.get("selection_set") == "hero"
        assert iso.get("muted_count", 0) >= 1
        assert ed._find_clip(other.id).muted is True
        assert ed._find_clip(keep.id).muted is False

        # restore mute for jl cut path
        ed._find_clip(other.id).muted = False
        ed.save_selection_set("hero2", [keep.id])
        jl = ed.selection_jl_cut_set("hero2", style="j", frames=6)
        assert jl.get("selection_set") == "hero2"
        assert jl.get("style") == "j"
        assert "count" in jl
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_43():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/isolate_selection_set" in app
    assert "/api/edit/selection_jl_cut_set" in app
    assert "def isolate_selection_set" in mcp
    assert "def selection_jl_cut_set" in mcp
    assert 'id="btn-isolate-set"' in html
    assert 'id="btn-jl-set"' in html
    assert "isolateSelectionSetUi" in ts
    assert "selectionJlCutSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "isolate_selection_set" in cat["tool_ids"]
    assert "selection_jl_cut_set" in cat["tool_ids"]
