"""export_selection_set_clips_pack + selection_set_track_states (0.9.81)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_clips_pack_and_track_states_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cliptrk_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        states = ed.selection_set_track_states("hero")
        assert states.get("selection_set") == "hero"
        assert states.get("count", 0) >= 1
        assert len(states.get("tracks") or []) >= 1

        pack = ed.export_selection_set_clips_pack("hero")
        assert pack.get("selection_set") == "hero"
        out = pack.get("output_dir") or pack.get("out_dir")
        assert out and Path(str(out)).is_dir()
        ok_items = [
            x for x in (pack.get("clips") or [])
            if x.get("ok") and x.get("path") and Path(str(x["path"])).is_file()
        ]
        assert pack.get("count", 0) >= 1 or len(ok_items) >= 1 or list(
            Path(str(out)).glob("*.mp4")
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_81():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_clips_pack" in app
    assert "/api/edit/selection_set_track_states" in app
    assert "def export_selection_set_clips_pack" in mcp
    assert "def selection_set_track_states" in mcp
    assert 'id="btn-exp-clips-pack-set"' in html
    assert 'id="btn-track-states-set"' in html
    assert "exportSelectionSetClipsPackUi" in ts
    assert "selectionSetTrackStatesUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_clips_pack" in cat["tool_ids"]
    assert "selection_set_track_states" in cat["tool_ids"]
