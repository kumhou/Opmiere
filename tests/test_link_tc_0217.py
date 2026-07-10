"""0.2.17: link_group, follow_links nudge/delete, detach link, TC helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.6) -> None:
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


def test_link_nudge_follow(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "red", 0.6)
    _vid(v2, "blue", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tv = ed.add_track("video")
    ta = ed.add_track("audio")
    c1 = ed.place_from_file(v1, "video", tv.id, 10)
    c2 = ed.place_from_file(v2, "audio", ta.id, 10)
    r = ed.link_clips([c1.id, c2.id])
    assert r["count"] == 2
    assert ed._find_clip(c1.id).link_group == ed._find_clip(c2.id).link_group
    g = ed.linked_group(c1.id)
    assert g["count"] == 2
    ed.nudge_clips([c1.id], 5, follow_links=True)
    assert ed._find_clip(c1.id).start == 15
    assert ed._find_clip(c2.id).start == 15
    # unlink one
    ed.unlink_clips([c2.id])
    assert ed._find_clip(c2.id).link_group is None
    ed.nudge_clips([c1.id], 5, follow_links=True)
    assert ed._find_clip(c1.id).start == 20
    assert ed._find_clip(c2.id).start == 15  # no longer linked


def test_detach_auto_link_and_tc(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "green", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    r = ed.detach_audio(c.id, link=True)
    assert r["link_group"]
    assert ed._find_clip(c.id).link_group == r["link_group"]
    assert ed._find_clip(r["audio_clip_id"]).link_group == r["link_group"]
    # delete follow links removes both
    ed.delete_clips([c.id], follow_links=True)
    assert ed.clips_on_track(tr.id)["count"] == 0

    tc = ed.frames_to_tc(90)  # 3s at 30fps
    assert tc["tc"] == "00:00:03:00"
    p = ed.tc_to_frames("00:00:03:00")
    assert p["frame"] == 90
    p2 = ed.tc_to_frames("1.5")
    assert p2["frame"] == 45


def test_web_link_tc(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 0.6)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    d = client.post("/api/clip/detach_audio", json={"clip_id": cid, "link": True})
    assert d.status_code == 200, d.text
    assert d.json()["link_group"]
    aid = d.json()["audio_clip_id"]
    r = client.post("/api/clips/linked", json={"clip_id": cid})
    assert r.status_code == 200
    assert r.json()["count"] == 2
    r = client.post("/api/clips/nudge", json={
        "clip_ids": [cid], "delta_frames": 3, "follow_links": True,
    })
    assert r.status_code == 200
    assert r.json()["count"] == 2
    r = client.post("/api/tc/format", json={"frame": 30})
    assert r.status_code == 200
    assert r.json()["tc"] == "00:00:01:00"
    r = client.post("/api/tc/parse", json={"tc": "00:00:01:00"})
    assert r.json()["frame"] == 30
    # unlink
    r = client.post("/api/clips/unlink", json={"clip_ids": [cid, aid]})
    assert r.status_code == 200
