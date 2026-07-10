"""0.2.1: split_all_at, link_transition, snap_points."""

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
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_split_all_at(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, "red", 1.0)
    _vid(b, "blue", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    v = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", v.id, 0)
    c2 = ed.place_from_file(b, "video", v.id, c1.end)
    # audio track overlapping middle
    w = tmp_path / "w.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1.0",
            "-c:a", "pcm_s16le", str(w),
        ],
        capture_output=True, text=True, check=True,
    )
    au = ed.add_track("audio")
    ed.place_from_file(w, "audio", au.id, 0)

    mid = c1.end // 2 if c1.end > 2 else 5
    # ensure mid is inside first video and audio
    mid = max(1, min(mid, c1.end - 1))
    r = ed.split_all_at(mid)
    assert r["split_count"] >= 2  # video + audio
    v_after = [t for t in ed.project.tracks if t.kind == "video"][0]
    assert len(v_after.clips) == 3  # c1 split + c2
    # one undo restores pre-razor state
    assert ed.undo()
    v_restored = [t for t in ed.project.tracks if t.kind == "video"][0]
    assert len(v_restored.clips) == 2


def test_link_transition(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, "teal", 0.8)
    _vid(b, "maroon", 0.8)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    c2 = ed.place_from_file(b, "video", tr.id, c1.end)
    r = ed.link_transition(c2.id, transition_type="cross_dissolve", duration_frames=6)
    assert r["transition"]["type"] == "cross_dissolve"
    c2b = ed._find_clip(c2.id)
    assert c2b.transition_in is not None
    assert c2b.start == c1.end - 6


def test_snap_points(tmp_path: Path):
    a = tmp_path / "a.mp4"
    _vid(a, "gray", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(a, "video", tr.id, 0)
    ed.add_marker(frame=10, label="x")
    pts = ed.snap_points()["frames"]
    assert 0 in pts
    assert c.start in pts
    assert c.end in pts
    assert 10 in pts
    tv = ed.timeline_view()
    assert "snap_frames" in tv


def test_web_razor_transition(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, "navy", 0.8)
    _vid(b, "olive", 0.8)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    r = client.post("/api/place_batch", json={
        "paths": [str(a), str(b)], "sequential": True,
    })
    assert r.status_code == 200, r.text
    placed = r.json()["result"]["placed"]
    assert len(placed) >= 2
    c2 = placed[1]["clip_id"]
    r = client.post("/api/transition", json={
        "right_clip_id": c2, "duration_frames": 4,
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/razor", json={"at_frame": 5})
    assert r.status_code == 200
    assert r.json()["split_count"] >= 1
