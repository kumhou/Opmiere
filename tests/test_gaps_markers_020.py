"""0.2.0: fill_track_gaps (black slug), markers, prepare_export."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor, Project
from opmiere.model import Marker

FPS = 30


def _clip(path: Path, color: str = "green", dur: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_marker_roundtrip():
    p = Project()
    m = p.add_marker(90, label="hook", color="#ff0")
    assert m.frame == 90
    d = p.to_dict()
    assert "markers" in d
    p2 = Project.from_dict(d)
    assert len(p2.markers) == 1
    assert p2.markers[0].label == "hook"


def test_fill_gaps_then_export(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _clip(a, "red", 0.4)
    _clip(b, "blue", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    # second clip with a hole (not contiguous)
    media = ed.import_media(b, "video")
    ed.add_clip(tr.id, media.id, c1.end + 15, 0, min(12, media.duration_frames))
    # export should fail without fill
    try:
        ed.export(tmp_path / "fail.mp4")
        raised = False
    except ValueError:
        raised = True
    assert raised

    filled = ed.fill_track_gaps(tr.id, mode="slug")
    assert filled["pad_count"] >= 1
    out = tmp_path / "ok.mp4"
    written = ed.export(out)
    assert Path(written).exists()
    assert Path(written).stat().st_size > 500


def test_prepare_export_and_finish(tmp_path: Path):
    a = tmp_path / "a.mp4"
    _clip(a, "navy", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(a, "video", tr.id, 10)  # head gap
    prep = ed.prepare_export()
    assert prep["fills"]
    # video-only sources: skip loudness normalize
    r = ed.finish_delivery(
        tmp_path / "fin.mp4",
        prepare=False,
        run_review=False,
        normalize_preset=None,
    )
    assert r["ok"]


def test_markers_api(tmp_path: Path):
    a = tmp_path / "a.mp4"
    _clip(a, "gray", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(a, "video", tr.id, 0)
    m = ed.add_marker(time_seconds=0.2, label="beat")
    assert m["frame"] > 0
    assert ed.list_markers()["count"] == 1
    tv = ed.timeline_view()
    assert len(tv["markers"]) == 1
    ed.delete_marker(m["id"])
    assert ed.list_markers()["count"] == 0


def test_web_fill_and_markers(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _clip(a)
    _clip(b, "orange")
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p1 = client.post("/api/place", json={"path": str(a), "kind": "video"})
    assert p1.status_code == 200
    # second via layout hole: place then move
    p2 = client.post("/api/place", json={"path": str(b), "kind": "video"})
    assert p2.status_code == 200
    # move second clip to create gap via layout
    cid2 = p2.json()["id"]
    client.post("/api/clip/layout", json={
        "clip_id": cid2,
        "start_frame": 40,
        "refresh_preview": False,
    })
    r = client.post("/api/fill_gaps", json={"mode": "slug"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["pad_count"] >= 1

    r = client.post("/api/markers", json={"time_seconds": 0.1, "label": "x"})
    assert r.status_code == 200
    assert len(r.json()["markers"]) >= 1
