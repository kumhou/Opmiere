"""validate_selection_set + repair_selection_set (0.7.6)."""

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
            "-f", "lavfi", "-i", f"color=c=red:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=180:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_validate_and_repair_selection_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_svr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        ed.save_selection_set("hero", [c.id])

        val = ed.validate_selection_set("hero")
        assert val.get("selection_set") == "hero"
        assert (val.get("loaded") or {}).get("clip_count") == 1
        assert "ok" in val

        rep = ed.repair_selection_set(
            "hero",
            unlock=True,
            ensure_proxies=False,
            pack_gaps=False,
        )
        assert rep.get("selection_set") == "hero"
        assert isinstance(rep.get("steps"), list)
        assert (rep.get("loaded") or {}).get("clip_ids") == [c.id]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_6():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/validate_selection_set" in app
    assert "/api/edit/repair_selection_set" in app
    assert "def validate_selection_set" in mcp
    assert "def repair_selection_set" in mcp
    assert 'id="btn-val-sel-set"' in html
    assert 'id="btn-rep-sel-set"' in html
    assert "validateSelectionSetUi" in ts
    assert "repairSelectionSetUi" in ts
