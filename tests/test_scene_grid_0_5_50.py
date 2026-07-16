"""scene_grid + transitions near markers + path-C wipe."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan


def _vid(path: Path, d: float = 2.0, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_markers_from_scenes_mocked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sc_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        ed.import_media(v, "video")
        fake = {
            "path": str(v),
            "backend": "mock",
            "scenes": [
                {"index": 0, "start": 0.0, "end": 0.5, "start_frame": 0, "end_frame": 15},
                {"index": 1, "start": 0.5, "end": 1.0, "start_frame": 15, "end_frame": 30},
                {"index": 2, "start": 1.0, "end": 2.0, "start_frame": 30, "end_frame": 60},
            ],
        }
        with mock.patch("opmiere.ops._detect_scenes", return_value=fake):
            r = ed.markers_from_scenes(label_prefix="Scene")
        # start=0 skipped by default → 0.5 and 1.0 → frames 15, 30
        assert r["count"] == 2
        frames = sorted(m.frame for m in ed.project.markers)
        assert frames == [15, 30]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scene_grid_both_mocked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sg_"))
    try:
        v = root / "v.mp4"
        _vid(v, 3.0)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        fake = {
            "path": str(v),
            "backend": "mock",
            "scenes": [
                {"index": 0, "start": 0.0, "end": 1.0, "start_frame": 0},
                {"index": 1, "start": 1.0, "end": 2.0, "start_frame": 30},
                {"index": 2, "start": 2.0, "end": 3.0, "start_frame": 60},
            ],
        }
        with mock.patch("opmiere.ops._detect_scenes", return_value=fake):
            r = ed.scene_grid(track_id=tr.id, mode="both", clear_existing_prefix=True)
        assert r["markers"]["count"] >= 1
        assert r["split"]["count"] >= 1
        assert len(ed.project.tracks[0].clips) > 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_apply_transitions_near_markers():
    root = Path(tempfile.mkdtemp(prefix="opmiere_xnm_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 1.5, "navy")
        _vid(b, 1.5, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, c1.end)
        # marker at the cut
        cut = c2.start
        ed.add_marker(frame=cut, label="Beat 1")
        r = ed.apply_transitions_near_markers(
            tr.id, transition_type="cross_dissolve", duration_frames=6, max_delta_frames=1,
        )
        assert r["count"] == 1
        assert ed._find_clip(c2.id).transition_in is not None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_wipe_maps():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wipe_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 1.0, "teal")
        _vid(b, 1.0, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, c1.end)
        ed.link_transition(c2.id, transition_type="wipe_left", duration_frames=8)
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 13
        assert int(ADAPTER_VERSION) >= 13
        assert "transition" in plan.get("mapped", [])
        by_id = {c["id"]: c for c in plan["clips"]}
        assert by_id[c2.id].get("wipe_in") == "left"
        assert int(by_id[c2.id].get("fade_in_frames") or 0) >= 8
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_50():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/scene_grid" in app
    assert "/api/markers/from_scenes" in app
    assert "/api/transitions/near_markers" in app
    assert "def scene_grid" in mcp
    assert "def apply_transitions_near_markers" in mcp
    assert 'id="btn-scene-grid"' in html
    assert 'id="btn-x-near-mkr"' in html
    assert "sceneGridUi" in ts
