"""solo_selection_set_tracks + clear_selection_set_effects (0.9.21)."""

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


def test_solo_tracks_and_clear_effects():
    root = Path(tempfile.mkdtemp(prefix="opmiere_scf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        solo = ed.solo_selection_set_tracks("hero", exclusive=True)
        assert solo.get("selection_set") == "hero"
        assert solo.get("count", 0) >= 1
        tr_rep = ed.selection_set_track_report("hero")
        assert tr_rep.get("solo_count", 0) >= 1

        ed.set_selection_set_fades("hero", fade_in_frames=3, fade_out_frames=3)
        clr = ed.clear_selection_set_effects("hero")
        assert clr.get("selection_set") == "hero"
        fades = ed.selection_set_fades_report("hero")
        assert fades.get("with_fades", 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_21():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/solo_selection_set_tracks" in app
    assert "/api/edit/clear_selection_set_effects" in app
    assert "def solo_selection_set_tracks" in mcp
    assert "def clear_selection_set_effects" in mcp
    assert 'id="btn-solo-set-tr"' in html
    assert 'id="btn-clr-fx-set"' in html
    assert "soloSelectionSetTracksUi" in ts
    assert "clearSelectionSetEffectsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "solo_selection_set_tracks" in cat["tool_ids"]
    assert "clear_selection_set_effects" in cat["tool_ids"]
