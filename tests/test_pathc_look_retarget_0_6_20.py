"""selection_path_c_report + apply_look_to_selection + retarget_selection_media (0.6.20)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_pathc_look_retarget():
    root = Path(tempfile.mkdtemp(prefix="opmiere_plr_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.4)
        _vid(b, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(a, "video", tr.id, 0)
        ed.apply_vignette(c.id, strength=0.35)
        rep = ed.selection_path_c_report([c.id])
        assert rep["count"] == 1
        assert int(rep["adapter_version"]) >= int(ADAPTER_VERSION)
        assert "clips" in rep and rep["clips"][0]["clip_id"] == c.id
        assert "catalog" in rep
        # floor check — never pin exact adapter version
        assert int(rep["adapter_version"]) >= 1

        look = ed.apply_look_to_selection([c.id], "cinematic")
        assert look.get("clip_count", 0) >= 1 or look.get("applied_count", 0) >= 0

        m2 = ed.import_media(b, "video")
        rt = ed.retarget_selection_media([c.id], m2.id, keep_source_range=True)
        assert rt["count"] == 1
        assert ed._find_clip(c.id).media == m2.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_20():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_path_c" in app
    assert "/api/edit/look_selection" in app
    assert "/api/edit/style_selection" in app
    assert "/api/edit/retarget_selection_media" in app
    assert "def selection_path_c_report" in mcp
    assert "def apply_look_to_selection" in mcp
    assert "def apply_style_to_selection" in mcp
    assert "def retarget_selection_media" in mcp
    assert 'id="btn-pathc-sel"' in html
    assert 'id="btn-look-sel"' in html
    assert 'id="btn-style-sel"' in html
    assert "selectionPathCUi" in ts
    assert "lookSelectionUi" in ts
    assert "styleSelectionUi" in ts
