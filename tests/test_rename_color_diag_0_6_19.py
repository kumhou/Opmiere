"""rename_selection + color_selection + selection_diagnostics (0.6.19)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_rename_color_diag():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rcd_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end))
        ed.apply_vignette(c1.id, strength=0.3)
        rn = ed.rename_selection([c1.id, c2.id], pattern="Shot {n:02d}", start=1)
        assert rn["count"] == 2
        assert ed._find_clip(c1.id).name == "Shot 01"
        assert ed._find_clip(c2.id).name == "Shot 02"
        col = ed.color_selection([c1.id, c2.id], "#ff006e")
        assert col["count"] == 2
        assert ed._find_clip(c1.id).color == "#ff006e"
        d = ed.selection_diagnostics([c1.id, c2.id])
        assert d["count"] == 2
        assert d["offline_count"] == 0
        assert d["effect_instances"] >= 1
        assert d["span"]["duration_frames"] > 0
        c1d = next(x for x in d["clips"] if x["clip_id"] == c1.id)
        assert "vignette" in c1d["effects"]
        assert c1d["media_online"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_19():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/rename_selection" in app
    assert "/api/edit/color_selection" in app
    assert "/api/edit/selection_diagnostics" in app
    assert "def rename_selection" in mcp
    assert "def color_selection" in mcp
    assert "def selection_diagnostics" in mcp
    assert 'id="btn-rename-sel"' in html
    assert 'id="btn-color-sel"' in html
    assert 'id="btn-diag-sel"' in html
    assert "renameSelectionUi" in ts
    assert "colorSelectionUi" in ts
    assert "selectionDiagnosticsUi" in ts
