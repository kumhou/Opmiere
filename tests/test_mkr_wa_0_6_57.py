"""export_selection_markers_default + export_work_area_mp4_default (0.6.57)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_markers_and_work_area_default():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mw_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=15)
        ed.add_marker(5, label="hit")
        ed.add_marker(40, label="outside")  # outside short selection span

        mkr = ed.export_selection_markers_default(
            [c.id], filename="sel_mkr.json", format="json",
        )
        p = Path(mkr.get("path") or "")
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        frames = [int(x["frame"]) for x in data.get("markers") or []]
        assert 5 in frames
        assert 40 not in frames
        assert int(mkr.get("count") or 0) >= 1

        # work area from selection, then default export
        ed.work_area_from_selection([c.id])
        wa = ed.export_work_area_mp4_default(
            filename="wa.mp4",
            normalize_preset=None,
            run_delivery_check=False,
        )
        # export_work_area / export_range may key path differently
        wp = Path(
            wa.get("path")
            or wa.get("output_path")
            or (ed.bundle.root / "exports" / "wa.mp4")
        )
        assert wp.is_file() or (ed.bundle.root / "exports" / "wa.mp4").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_57():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_markers_default" in app
    assert "/api/edit/export_work_area_mp4_default" in app
    assert "def export_selection_markers_default" in mcp
    assert "def export_work_area_mp4_default" in mcp
    assert 'id="btn-mkr-sel-exp"' in html
    assert 'id="btn-wa-mp4-def"' in html
    assert "exportSelectionMarkersDefaultUi" in ts
    assert "exportWorkAreaMp4DefaultUi" in ts
