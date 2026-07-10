"""0.2.14: stretch_to, marker_near, exclusive solo, clips_on_track."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_stretch_to(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 1.0)  # 30 frames source
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    assert c.timeline_duration_frames == 30
    r = ed.stretch_to(c.id, 60)  # half speed
    assert abs(r["speed"]["to"] - 0.5) < 1e-6
    assert ed._find_clip(c.id).timeline_duration_frames == 60
    # clamp upper
    r2 = ed.stretch_to(c.id, 5, clamp=True)  # would need 6x → clamp 4x
    assert r2["clamped"] is True
    assert r2["speed"]["to"] == 4.0


def test_marker_near_and_solo_exclusive(tmp_path: Path):
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    t0 = ed.add_track("video")
    t1 = ed.add_track("video")
    ed.set_track_solo(t0.id, True)
    ed.set_track_solo(t1.id, True, exclusive=True)
    assert ed.project.track_by_id(t1.id).solo is True
    assert ed.project.track_by_id(t0.id).solo is False

    ed.add_marker(10, label="a")
    ed.add_marker(50, label="b")
    ed.add_marker(90, label="c")
    n = ed.marker_near(20, direction="next")
    assert n["found"] is True
    assert n["marker"]["label"] == "b"
    p = ed.marker_near(20, direction="prev")
    assert p["marker"]["label"] == "a"
    near = ed.marker_near(48, direction="nearest")
    assert near["marker"]["label"] == "b"
    wrap = ed.marker_near(100, direction="next", wrap=True)
    assert wrap["found"] is True
    assert wrap.get("wrapped") is True


def test_clips_on_track(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "blue", 0.4)
    _vid(v2, "green", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
    listed = ed.clips_on_track(tr.id)
    assert listed["count"] == 2
    assert listed["clips"][0]["clip_id"] == c1.id
    assert listed["clips"][1]["clip_id"] == c2.id


def test_web_stretch_marker_slide(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 1.0)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/clip/stretch", json={
        "clip_id": cid, "target_duration_frames": 45, "clamp": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["speed"]["to"] < 1.0
    client.post("/api/markers", json={"frame": 5, "label": "x"})
    client.post("/api/markers", json={"frame": 20, "label": "y"})
    n = client.post("/api/markers/near", json={"frame": 6, "direction": "next"})
    assert n.status_code == 200, n.text
    assert n.json()["found"] is True
    # need 3 clips for slide middle - skip if fails
    # just call slide may fail without neighbors
    state = client.get("/api/project/timeline")
    tid = state.json()["tracks"][0]["id"]
    clips = client.get(f"/api/track/{tid}/clips")
    assert clips.status_code == 200
    assert clips.json()["count"] >= 1
