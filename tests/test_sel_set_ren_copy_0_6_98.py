"""rename_selection_set + copy_selection_set (0.6.98)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=maroon:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=410:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_rename_and_copy_selection_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, 8, duration_frames=8)
        ed.save_selection_set("draft", [c1.id, c2.id], note="wip")

        copied = ed.copy_selection_set("draft", "draft_bak", overwrite=True)
        assert copied.get("ok") is True
        assert copied.get("dest") == "draft_bak"
        assert set(copied["clip_ids"]) == {c1.id, c2.id}

        ren = ed.rename_selection_set("draft", "hero", overwrite=False)
        assert ren.get("ok") is True
        assert ren.get("old_name") == "draft"
        assert ren.get("new_name") == "hero"

        names = {s["name"] for s in ed.list_selection_sets()["sets"]}
        assert "draft" not in names
        assert "hero" in names
        assert "draft_bak" in names

        loaded = ed.load_selection_set("hero", set_work_area=False)
        assert set(loaded["clip_ids"]) == {c1.id, c2.id}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_98():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/rename_selection_set" in app
    assert "/api/edit/copy_selection_set" in app
    assert "def rename_selection_set" in mcp
    assert "def copy_selection_set" in mcp
    assert 'id="btn-ren-sel-set"' in html
    assert 'id="btn-copy-sel-set"' in html
    assert "renameSelectionSetUi" in ts
    assert "copySelectionSetUi" in ts
