"""save_selection_set + load_selection_set (0.6.95)."""

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
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_save_load_list_delete_selection_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ss_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)

        saved = ed.save_selection_set(
            "hero",
            [c1.id, c2.id],
            note="hero cut",
        )
        assert saved.get("ok") is True
        assert saved.get("clip_count") == 2
        assert Path(saved["path"]).is_file()

        listed = ed.list_selection_sets()
        assert listed.get("count") == 1
        assert listed["sets"][0]["name"] == "hero"

        loaded = ed.load_selection_set("hero", set_work_area=True)
        assert loaded.get("ok") is True
        assert set(loaded.get("clip_ids") or []) == {c1.id, c2.id}
        assert loaded.get("missing_count") == 0
        wa = loaded.get("work_area") or {}
        assert wa.get("ready") is True

        data = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
        assert "hero" in data.get("sets", {})

        deleted = ed.delete_selection_set("hero")
        assert deleted.get("ok") is True
        assert deleted.get("remaining") == []
        assert ed.list_selection_sets().get("count") == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_drops_missing_clips():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ss2_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)
        ed.save_selection_set("both", [c1.id, c2.id])
        ed.delete_clip(c2.id)
        loaded = ed.load_selection_set("both", set_work_area=False)
        assert loaded["clip_ids"] == [c1.id]
        assert loaded["missing_count"] == 1
        assert c2.id in (loaded.get("missing") or [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_95():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/save_selection_set" in app
    assert "/api/edit/load_selection_set" in app
    assert "/api/edit/list_selection_sets" in app
    assert "/api/edit/delete_selection_set" in app
    assert "def save_selection_set" in mcp
    assert "def load_selection_set" in mcp
    assert "def list_selection_sets" in mcp
    assert "def delete_selection_set" in mcp
    assert 'id="btn-save-sel-set"' in html
    assert 'id="btn-load-sel-set"' in html
    assert "saveSelectionSetUi" in ts
    assert "loadSelectionSetUi" in ts
