"""markers_from_beats + path-C shape_mask + FCPXML markers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path, color: str = "navy", d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _wav(path: Path, seconds: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def test_markers_from_beats_mocked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_beats_"))
    try:
        wav = root / "m.wav"
        _wav(wav, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        ed.import_media(wav, "audio")
        fake = {
            "beat_times": [0.5, 1.0, 1.5],
            "bpm_estimate": 120.0,
        }
        with mock.patch("opmiere.ops._detect_beats", return_value=fake):
            r = ed.markers_from_beats(label_prefix="Beat")
        assert r["count"] == 3
        assert r["bpm_estimate"] == 120.0
        frames = sorted(m.frame for m in ed.project.markers)
        assert frames == [15, 30, 45]
        assert all(m.label.startswith("Beat") for m in ed.project.markers)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_shape_mask_maps_to_crop():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mask_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(
            c.id,
            {
                "type": "shape_mask",
                "shape": "circle",
                "cx": 0.5,
                "cy": 0.5,
                "size": 0.6,
                "feather": 0.05,
            },
        )
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "shape_mask" in vis["mapped_effects"]
        assert vis["crop"] is not None
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 11
        assert int(ADAPTER_VERSION) >= 11
        assert "shape_mask" in plan.get("mapped", [])
        assert plan["clips"][0].get("crop")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_fcpxml_markers_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fcp_m_"))
    try:
        v = root / "a.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=12, label="chapter", color="#00ff00")
        body = ed.export_fcpxml()["body"]
        assert "<marker " in body
        assert "chapter" in body
        assert ed.export_fcpxml().get("marker_count") == 1

        ed2 = Editor.create(root / "p2.opm", fps=30, width=320, height=180)
        r = ed2.import_fcpxml(text=body, import_missing_media=True)
        assert r["count"] == 1
        assert r.get("markers_imported", 0) == 1
        assert any(m.label == "chapter" for m in ed2.project.markers)
        assert ed2.project.markers[0].frame == 12
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_46():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/markers/from_beats" in app
    assert "def markers_from_beats" in mcp
    assert 'id="btn-beat-mkr"' in html
    assert "markersFromBeatsUi" in ts
