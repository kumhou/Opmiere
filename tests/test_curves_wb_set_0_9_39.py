"""curves_selection_set + white_balance_selection_set (0.9.39)."""

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


def test_curves_and_white_balance_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cwb_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        curves = ed.curves_selection_set("hero", preset="increase_contrast")
        assert curves.get("selection_set") == "hero"
        assert curves.get("preset") == "increase_contrast"

        wb = ed.white_balance_selection_set(
            "hero", temperature=5200.0, mix=0.8,
        )
        assert wb.get("selection_set") == "hero"
        fx = ed.selection_set_effects_report("hero")
        assert fx.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_39():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/curves_selection_set" in app
    assert "/api/edit/white_balance_selection_set" in app
    assert "def curves_selection_set" in mcp
    assert "def white_balance_selection_set" in mcp
    assert 'id="btn-curves-set"' in html
    assert 'id="btn-wb-set"' in html
    assert "curvesSelectionSetUi" in ts
    assert "whiteBalanceSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "curves_selection_set" in cat["tool_ids"]
    assert "white_balance_selection_set" in cat["tool_ids"]
