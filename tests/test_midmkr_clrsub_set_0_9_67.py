"""markers_at_selection_set_mids + clear_selection_set_subtitles (0.9.67)."""

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


def test_mid_markers_and_clear_subtitles_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_midsub_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        # inject a subtitles effect then clear via set wrapper
        with ed._mutate():
            clip = ed._find_clip(c.id)
            fx = list(clip.effects or [])
            fx.append({"type": "subtitles", "text": "hi"})
            clip.effects = fx

        mk = ed.markers_at_selection_set_mids("hero", prefix="Mid ")
        assert mk.get("selection_set") == "hero"
        assert int(mk.get("count") or 0) >= 1

        clr = ed.clear_selection_set_subtitles("hero")
        assert clr.get("selection_set") == "hero"
        assert int(clr.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "subtitles" not in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_67():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/markers_at_selection_set_mids" in app
    assert "/api/edit/clear_selection_set_subtitles" in app
    assert "def markers_at_selection_set_mids" in mcp
    assert "def clear_selection_set_subtitles" in mcp
    assert 'id="btn-mid-mkr-set"' in html
    assert 'id="btn-clr-sub-set"' in html
    assert "markersAtSelectionSetMidsUi" in ts
    assert "clearSelectionSetSubtitlesUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "markers_at_selection_set_mids" in cat["tool_ids"]
    assert "clear_selection_set_subtitles" in cat["tool_ids"]
