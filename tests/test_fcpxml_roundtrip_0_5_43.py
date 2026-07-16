"""FCPXML export/import round-trip + path-C curves mapping."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d=1.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_fcpxml_export_import_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fcp_"))
    try:
        v1 = root / "a.mp4"
        v2 = root / "b.mp4"
        _vid(v1, "navy")
        _vid(v2, "olive")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v1, "video", tr.id, 0)
        ed.place_from_file(v2, "video", tr.id, c1.end)
        ed.project.tracks[0].clips[0].name = "shotA"
        body = ed.export_fcpxml()["body"]
        assert "asset-clip" in body
        assert "file:///" in body

        ed2 = Editor.create(root / "p2.opm", fps=30, width=320, height=180)
        r = ed2.import_fcpxml(text=body, import_missing_media=True)
        assert r["count"] == 2
        assert r["skipped_count"] == 0
        names = [c.name for c in ed2.project.tracks[0].clips_in_order()]
        assert "shotA" in names
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_maps_curves_preset():
    root = Path(tempfile.mkdtemp(prefix="opmiere_curves_"))
    try:
        v = root / "v.mp4"
        _vid(v, "gray")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "curves", "preset": "lighter"})
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "curves" in vis["mapped_effects"]
        assert vis["brightness"] > 0
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 10
        assert int(ADAPTER_VERSION) >= 10
        assert "curves" in plan.get("mapped", [])
        assert float(plan["clips"][0].get("brightness") or 0) > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_43():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/import/fcpxml" in app
    assert "def import_fcpxml" in mcp
    assert 'id="btn-import-fcpxml"' in html
    assert "importFcpxmlFile" in ts
