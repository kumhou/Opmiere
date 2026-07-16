"""OTIO-like JSON export/import round-trip + path-C dissolve mapping."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan


def _vid(path: Path, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d=1.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_otio_export_import_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_otio_"))
    try:
        v1 = root / "a.mp4"
        v2 = root / "b.mp4"
        _vid(v1, "navy")
        _vid(v2, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v1, "video", tr.id, 0)
        c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
        ed.set_clip_meta(c1.id, name="shotA") if hasattr(ed, "set_clip_meta") else None
        # name via direct field if available
        ed.project.tracks[0].clips[0].name = "shotA"
        ed.project.tracks[0].clips[1].name = "shotB"
        exported = ed.export_otio_json()
        assert exported["count"] == 2
        body = exported["body"]
        doc = json.loads(body)
        assert doc["OTIO_SCHEMA"] == "Timeline.1"

        # New project: import via text (media still on disk)
        ed2 = Editor.create(root / "p2.opm", fps=30, width=320, height=180)
        r = ed2.import_otio_json(text=body, import_missing_media=True)
        assert r["count"] == 2
        assert r["skipped_count"] == 0
        assert len(ed2.project.media) >= 2
        clips = ed2.project.tracks[0].clips_in_order()
        assert len(clips) == 2
        assert clips[0].name == "shotA"
        assert clips[1].start >= clips[0].start
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_maps_cross_dissolve():
    root = Path(tempfile.mkdtemp(prefix="opmiere_xfade_"))
    try:
        v1 = root / "a.mp4"
        v2 = root / "b.mp4"
        _vid(v1, "teal")
        _vid(v2, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v1, "video", tr.id, 0)
        c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
        ed.link_transition(c2.id, transition_type="cross_dissolve", duration_frames=8)
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 9
        assert int(ADAPTER_VERSION) >= 9
        assert "transition" in plan.get("mapped", [])
        # right clip fade in, left fade out
        by_id = {c["id"]: c for c in plan["clips"]}
        # after transition, c2 id may still match
        right = by_id.get(c2.id) or plan["clips"][-1]
        left = by_id.get(c1.id) or plan["clips"][0]
        assert int(right.get("fade_in_frames") or 0) >= 8
        assert int(left.get("fade_out_frames") or 0) >= 8
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_42():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/import/otio" in app
    assert "def import_otio_json" in mcp
    assert 'id="btn-import-otio"' in html
    assert "importOtioFile" in ts


def test_otio_markers_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_otio_m_"))
    try:
        v = root / "a.mp4"
        _vid(v, "navy")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=15, label="beat", color="#ff0000")
        body = ed.export_otio_json()["body"]
        doc = json.loads(body)
        assert len(doc.get("markers") or []) == 1
        assert doc["markers"][0]["name"] == "beat"

        ed2 = Editor.create(root / "p2.opm", fps=30, width=320, height=180)
        r = ed2.import_otio_json(text=body, import_missing_media=True)
        assert r["count"] == 1
        assert r.get("markers_imported", 0) == 1
        assert any(m.label == "beat" for m in ed2.project.markers)
        assert ed2.project.markers[0].frame == 15
    finally:
        shutil.rmtree(root, ignore_errors=True)
