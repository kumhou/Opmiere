"""export_edit_manifest + path-C audio DSP mapping."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_export_edit_manifest():
    root = Path(tempfile.mkdtemp(prefix="opmiere_man_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "blur", "amount": 1.5})
        ed.add_marker(frame=10, label="cut")
        out = root / "manifest.json"
        r = ed.export_edit_manifest(out)
        assert r["clip_count"] == 1
        assert r["marker_count"] == 1
        assert out.is_file()
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["schema"] == "opmiere.edit_manifest.v1"
        assert doc["tracks"][0]["clips"][0]["effects"][0]["type"] == "blur"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_audio_dsp_mapped():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dsp_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(
            c.id,
            {
                "type": "compression",
                "ratio": 4.0,
                "threshold_db": -18.0,
            },
        )
        ed.apply_effect(c.id, {"type": "noise_reduction", "amount": 12.0})
        ed.apply_effect(
            c.id,
            {"type": "audio_eq", "frequency_hz": 120.0, "gain_db": -3.0, "q": 0.7},
        )
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        for kind in ("compression", "noise_reduction", "audio_eq"):
            assert kind in vis["mapped_effects"]
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 19
        assert int(ADAPTER_VERSION) >= 19
        assert plan["clips"][0].get("compression", {}).get("ratio") == 4.0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_62():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/manifest" in app
    assert "def export_edit_manifest" in mcp
    assert 'id="btn-manifest"' in html
    assert "exportManifestUi" in ts
