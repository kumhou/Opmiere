"""selection_set_to_new_track + export_selection_set_handoff (0.8.3)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=violet:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=100:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_set_to_track_and_handoff():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sth_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, 8, duration_frames=8)
        ed.save_selection_set("hero", [c1.id, c2.id], note="h")

        moved = ed.selection_set_to_new_track(
            "hero", track_name="HeroV", preserve_starts=True,
        )
        assert moved.get("ok") is True
        assert moved.get("new_track_id")
        assert moved.get("track_name") == "HeroV"
        # clips now on new track
        for cid in [c1.id, c2.id]:
            trk, _ = ed._find_clip_and_track(cid)
            assert trk.id == moved["new_track_id"]

        hand = ed.export_selection_set_handoff(
            "hero",
            include_interchange=False,
        )
        assert hand.get("ok") is True
        out = Path(hand["out_dir"])
        assert out.is_dir()
        meta = Path(hand["meta_path"])
        assert meta.is_file()
        data = json.loads(meta.read_text(encoding="utf-8"))
        assert data.get("selection_set") == "hero"
        assert data.get("clip_count") == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_3():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_to_new_track" in app
    assert "/api/edit/export_selection_set_handoff" in app
    assert "def selection_set_to_new_track" in mcp
    assert "def export_selection_set_handoff" in mcp
    assert 'id="btn-set-new-trk"' in html
    assert 'id="btn-set-handoff"' in html
    assert "selectionSetToNewTrackUi" in ts
    assert "exportSelectionSetHandoffUi" in ts
