"""selection_set_agent_preflight + selection_set_checklist (0.9.3)."""

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
            "-f", "lavfi", "-i", f"color=c=darkslategray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=120:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_preflight_and_checklist_in_memory():
    root = Path(tempfile.mkdtemp(prefix="opmiere_spc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        pre = ed.selection_set_agent_preflight("hero")
        assert pre.get("selection_set") == "hero"
        assert (pre.get("loaded") or {}).get("clip_count") == 1
        assert "next_steps" in pre or "ok" in pre

        cl = ed.selection_set_checklist("hero")
        assert cl.get("selection_set") == "hero"
        assert cl.get("clip_count") == 1
        assert isinstance(cl.get("items"), list) or "items" in cl or "ok" in cl
        # in-memory — no new export file required
        exports = Path(ed.bundle.root) / "exports"
        if exports.is_dir():
            # checklist export is a different tool
            assert not list(exports.glob("*checklist*"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_3():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_agent_preflight" in app
    assert "/api/edit/selection_set_checklist" in app
    assert "def selection_set_agent_preflight" in mcp
    assert "def selection_set_checklist" in mcp
    assert 'id="btn-set-pre"' in html
    assert 'id="btn-set-clist"' in html
    assert "selectionSetAgentPreflightUi" in ts
    assert "selectionSetChecklistUi" in ts
    # catalog lists new tools
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_agent_preflight" in cat["tool_ids"]
    assert "selection_set_checklist" in cat["tool_ids"]
