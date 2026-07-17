"""clipboard_copy_selection_set + selection_set_diagnostics (0.9.46)."""

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


def test_clipboard_copy_and_diagnostics_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        copied = ed.clipboard_copy_selection_set("hero")
        assert copied.get("selection_set") == "hero"
        assert copied.get("count", 0) >= 1
        assert copied.get("origin_frame") is not None

        # CRUD copy_selection_set still works (source → dest)
        crud = ed.copy_selection_set("hero", "hero_copy")
        assert crud.get("dest") == "hero_copy" or "hero_copy" in str(crud)

        diag = ed.selection_set_diagnostics("hero")
        assert diag.get("selection_set") == "hero"
        assert diag.get("count", 0) >= 1
        assert diag.get("offline_count", 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_46():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/clipboard_copy_selection_set" in app
    assert "/api/edit/selection_set_diagnostics" in app
    assert "def clipboard_copy_selection_set" in mcp
    assert "def selection_set_diagnostics" in mcp
    assert 'id="btn-cb-copy-set"' in html
    assert 'id="btn-diag-set"' in html
    assert "clipboardCopySelectionSetUi" in ts
    assert "selectionSetDiagnosticsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "clipboard_copy_selection_set" in cat["tool_ids"]
    assert "selection_set_diagnostics" in cat["tool_ids"]
    # CRUD name still present
    assert "copy_selection_set" in cat["tool_ids"]
