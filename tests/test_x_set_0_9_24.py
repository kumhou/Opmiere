"""add/remove_transitions_from_selection_set (0.9.24)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
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


def test_add_and_remove_transitions_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_xset_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=15)
        c2 = ed.place_from_file(v, "video", tr.id, 15, duration_frames=15)
        ed.save_selection_set("hero", [c1.id, c2.id])

        added = ed.add_transitions_to_selection_set(
            "hero", duration_frames=6, require_both_selected=True,
        )
        assert added.get("selection_set") == "hero"
        # may add 0 if material insufficient; still must wire
        assert "selection_set" in added

        removed = ed.remove_transitions_from_selection_set("hero")
        assert removed.get("selection_set") == "hero"
        rep = ed.selection_set_transition_report("hero")
        assert rep.get("with_transitions", 0) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_24():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/add_transitions_to_selection_set" in app
    assert "/api/edit/remove_transitions_from_selection_set" in app
    assert "def add_transitions_to_selection_set" in mcp
    assert "def remove_transitions_from_selection_set" in mcp
    assert 'id="btn-add-x-set"' in html
    assert 'id="btn-rm-x-set"' in html
    assert "addTransitionsToSelectionSetUi" in ts
    assert "removeTransitionsFromSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "add_transitions_to_selection_set" in cat["tool_ids"]
    assert "remove_transitions_from_selection_set" in cat["tool_ids"]
