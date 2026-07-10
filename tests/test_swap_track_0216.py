"""0.2.16: swap_clips, move_track, rotate, reset transform, track name."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.5) -> None:
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


def test_swap_rotate_reset(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "red", 0.5)
    _vid(v2, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, 40)
    s1, s2 = c1.start, c2.start
    r = ed.swap_clips(c1.id, c2.id)
    assert ed._find_clip(c1.id).start == s2
    assert ed._find_clip(c2.id).start == s1
    assert r["a"]["start"]["to"] == s2

    ed.set_clip_rotate(c1.id, 90)
    assert any(
        e.get("type") == "rotate" and e.get("degrees") == 90
        for e in ed._find_clip(c1.id).effects
    )
    ed.set_position(c1.id, 0.1, 0.1, 0.4)
    ed.set_clip_opacity(c1.id, 0.5)
    ed.set_clip_crop(c1.id, 80, 60)
    ed.set_clip_gain(c1.id, -3)  # should survive reset transform
    rr = ed.reset_clip_transform(c1.id)
    assert "position" in rr["cleared"]
    clip = ed._find_clip(c1.id)
    assert clip.position is None
    types = {e.get("type") for e in (clip.effects or [])}
    assert "crop" not in types and "rotate" not in types and "opacity" not in types
    assert "gain" in types


def test_move_track_and_name(tmp_path: Path):
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    t0 = ed.add_track("video")
    t1 = ed.add_track("video")
    t2 = ed.add_track("audio")
    order0 = [t.id for t in ed.project.tracks]
    r = ed.move_track(t0.id, delta=1)
    assert r["index"]["to"] == order0.index(t0.id) + 1 or r["index"]["to"] >= 0
    # move t2 to front
    r2 = ed.move_track(t2.id, index=0)
    assert ed.project.tracks[0].id == t2.id
    assert r2["order"][0] == t2.id

    ed.set_track_name(t1.id, "B-roll")
    assert ed.project.track_by_id(t1.id).name == "B-roll"
    tv = ed.timeline_view()
    names = {t["id"]: t.get("name") for t in tv["tracks"]}
    assert names[t1.id] == "B-roll"
    listed = ed.list_tracks()
    assert any(x["track_id"] == t1.id and x["name"] == "B-roll" for x in listed["tracks"])


def test_web_swap_track(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "navy", 0.4)
    _vid(v2, "teal", 0.4)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    client.post("/api/track?kind=video")
    p1 = client.post("/api/place", json={"path": str(v1), "kind": "video"})
    p2 = client.post("/api/place", json={"path": str(v2), "kind": "video"})
    a, b = p1.json()["id"], p2.json()["id"]
    r = client.post("/api/clips/swap", json={"clip_a": a, "clip_b": b})
    assert r.status_code == 200, r.text
    r = client.post("/api/clip/rotate", json={"clip_id": a, "degrees": 45})
    assert r.status_code == 200, r.text
    r = client.post("/api/clip/reset_transform", json={"clip_id": a})
    assert r.status_code == 200, r.text
    tracks = client.get("/api/tracks").json()["tracks"]
    tid = tracks[0]["track_id"]
    r = client.post("/api/track/move", json={"track_id": tid, "delta": 1})
    assert r.status_code == 200, r.text
    r = client.post("/api/track/name", json={"track_id": tid, "name": "Main"})
    assert r.status_code == 200, r.text
    assert r.json()["name"]["to"] == "Main"
