"""export_selection_sets + import_selection_sets (0.6.99)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=390:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_import_selection_sets_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_io_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=8)
        c2 = ed.place_from_file(v, "video", tr.id, 8, duration_frames=8)
        ed.save_selection_set("hero", [c1.id], note="h")
        ed.save_selection_set("broll", [c2.id], note="b")

        exp = ed.export_selection_sets(resolve_live=False)
        assert exp.get("ok") is True
        assert exp.get("count") == 2
        path = Path(exp["path"])
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "hero" in data["sets"] and "broll" in data["sets"]

        # wipe sets then import
        ed.delete_selection_set("hero")
        ed.delete_selection_set("broll")
        assert ed.list_selection_sets()["count"] == 0

        imp = ed.import_selection_sets(
            path, mode="merge", overwrite=True, resolve_live=True,
        )
        assert imp.get("ok") is True
        assert imp.get("imported_count") == 2
        names = {s["name"] for s in ed.list_selection_sets()["sets"]}
        assert names == {"hero", "broll"}
        assert set(ed.load_selection_set("hero", set_work_area=False)["clip_ids"]) == {
            c1.id
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_99():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_sets" in app
    assert "/api/edit/import_selection_sets" in app
    assert "def export_selection_sets" in mcp
    assert "def import_selection_sets" in mcp
    assert 'id="btn-exp-sel-sets"' in html
    assert 'id="btn-imp-sel-sets"' in html
    assert "exportSelectionSetsUi" in ts
    assert "importSelectionSetsUi" in ts
