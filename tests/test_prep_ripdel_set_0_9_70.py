"""prepare_selection_set_export + ripple_delete_selection_set (0.9.70)."""

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


def test_prepare_export_and_ripple_delete_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_preprip_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 12, duration_frames=12)
        ed.save_selection_set("hero", [c1.id])
        ed.save_selection_set("doomed", [c2.id])

        prep = ed.prepare_selection_set_export(
            "hero",
            unlock_tracks=True,
            export_set_work_area=True,
            pack_gaps=False,
        )
        assert prep.get("selection_set") == "hero"
        assert "preflight" in prep or "soft_ready" in prep

        deleted = ed.ripple_delete_selection_set("doomed")
        assert deleted.get("selection_set") == "doomed"
        assert int(deleted.get("count") or 0) >= 1
        try:
            ed._find_clip(c2.id)
            assert False, "expected clip removed"
        except Exception:
            pass
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_70():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/prepare_selection_set_export" in app
    assert "/api/edit/ripple_delete_selection_set" in app
    assert "def prepare_selection_set_export" in mcp
    assert "def ripple_delete_selection_set" in mcp
    assert 'id="btn-prep-exp-set"' in html
    assert 'id="btn-rip-del-set"' in html
    assert "prepareSelectionSetExportUi" in ts
    assert "rippleDeleteSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "prepare_selection_set_export" in cat["tool_ids"]
    assert "ripple_delete_selection_set" in cat["tool_ids"]
