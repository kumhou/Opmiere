"""balance_selection_set_gains + name_selection_set_from_media (0.9.90)."""

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


def test_balance_gains_and_name_from_media_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_balname_"))
    try:
        v = root / "clip_alpha.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c.name = "old_name"
        ed.save_selection_set("hero", [c.id])

        bal = ed.balance_selection_set_gains("hero", target_db=0.0, relative=True)
        assert bal.get("selection_set") == "hero"
        assert bal.get("count", 0) >= 1

        ren = ed.name_selection_set_from_media("hero", strip_ext=True)
        assert ren.get("selection_set") == "hero"
        assert ren.get("count", 0) >= 1
        clip = ed._find_clip(c.id)
        assert clip.name != "old_name"
        assert "clip_alpha" in str(clip.name)
        rows = ren.get("renamed") or []
        assert rows and rows[0].get("to")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_90():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/balance_selection_set_gains" in app
    assert "/api/edit/name_selection_set_from_media" in app
    assert "def balance_selection_set_gains" in mcp
    assert "def name_selection_set_from_media" in mcp
    assert 'id="btn-balance-gains-set"' in html
    assert 'id="btn-name-from-media-set"' in html
    assert "balanceSelectionSetGainsUi" in ts
    assert "nameSelectionSetFromMediaUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "balance_selection_set_gains" in cat["tool_ids"]
    assert "name_selection_set_from_media" in cat["tool_ids"]
