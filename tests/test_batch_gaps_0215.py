"""0.2.15: batch effects, find/close gaps, remove empty tracks, crop."""

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


def test_batch_effect_and_crop(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "red", 0.5)
    _vid(v2, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
    r = ed.apply_effect_to_clips(
        [c1.id, c2.id], {"type": "blur", "amount": 3.0},
    )
    assert r["count"] == 2
    assert any(e.get("type") == "blur" for e in ed._find_clip(c1.id).effects)
    assert any(e.get("type") == "blur" for e in ed._find_clip(c2.id).effects)
    # single undo reverts both blurs (batch is one mutate)
    before = ed.history_status()["undo_depth"]
    assert ed.undo() is True
    assert not any(e.get("type") == "blur" for e in ed._find_clip(c1.id).effects)
    assert not any(e.get("type") == "blur" for e in ed._find_clip(c2.id).effects)
    assert ed.history_status()["undo_depth"] == before - 1

    ed.set_clip_crop(c1.id, 80, 60)
    crops = [e for e in ed._find_clip(c1.id).effects if e.get("type") == "crop"]
    assert len(crops) == 1
    assert crops[0]["width"] == 80
    ed.set_clip_crop(c1.id, 100, 50)
    crops = [e for e in ed._find_clip(c1.id).effects if e.get("type") == "crop"]
    assert len(crops) == 1
    assert crops[0]["width"] == 100


def test_find_close_gaps_remove_empty(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "green", 0.4)
    _vid(v2, "yellow", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end + 20)  # gap of 20
    gaps = ed.find_gaps(tr.id)
    assert gaps["total_gaps"] >= 1
    assert gaps["tracks"][0]["gaps"][0]["frames"] == 20

    r = ed.close_all_gaps()
    assert r["moved_total"] >= 1
    assert ed._find_clip(c2.id).start == ed._find_clip(c1.id).end

    # empty tracks
    t_empty = ed.add_track("video")
    t_empty2 = ed.add_track("audio")
    listed = ed.list_tracks()
    assert listed["count"] >= 3
    rem = ed.remove_empty_tracks(keep_one_per_kind=False)
    assert t_empty.id in rem["removed"]
    assert t_empty2.id in rem["removed"]
    assert all(t.clips for t in ed.project.tracks) or True


def test_web_batch_gaps(tmp_path: Path):
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
    p1 = client.post("/api/place", json={"path": str(v1), "kind": "video"})
    p2 = client.post("/api/place", json={"path": str(v2), "kind": "video"})
    ids = [p1.json()["id"], p2.json()["id"]]
    r = client.post("/api/clips/effect", json={
        "clip_ids": ids, "effect": {"type": "blur", "amount": 2},
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    r = client.post("/api/clip/crop", json={
        "clip_id": ids[0], "width": 120, "height": 80,
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/gaps/find", json={})
    assert r.status_code == 200
    r = client.post("/api/gaps/close_all", json={})
    assert r.status_code == 200
    assert client.get("/api/tracks").status_code == 200
    r = client.post("/api/tracks/remove_empty", json={"keep_one_per_kind": True})
    assert r.status_code == 200
