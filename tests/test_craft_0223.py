"""0.2.23: join_clips, set_clips_speed, trim_to_range, auto_link_av, set_clips_meta."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 2.0) -> None:
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


def test_join_speed_trim_link_meta(tmp_path: Path):
    v = tmp_path / "long.mp4"
    _vid(v, "red", 2.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    # split into three then join first two
    ed.split_clip(c.id, 20)
    left = ed.clips_on_track(tr.id)["clips"][0]["clip_id"]
    mid = ed.clips_on_track(tr.id)["clips"][1]["clip_id"]
    ed.split_clip(mid, 40)
    a = ed.clips_on_track(tr.id)["clips"][0]["clip_id"]
    b = ed.clips_on_track(tr.id)["clips"][1]["clip_id"]
    j = ed.join_clips(a, b)
    assert j["removed_clip_id"] == b
    assert ed._find_clip(j["clip_id"]).src_out == 40
    assert ed.clips_on_track(tr.id)["count"] == 2

    # batch speed
    ids = [x["clip_id"] for x in ed.clips_on_track(tr.id)["clips"]]
    sp = ed.set_clips_speed(ids, 2.0)
    assert sp["count"] == 2
    assert all(ed._find_clip(i).speed == 2.0 for i in ids)

    # trim_to_range normal on a long clip
    ed3 = Editor.create(tmp_path / "p3.opm", fps=FPS, width=160, height=90)
    t3 = ed3.add_track("video")
    c3 = ed3.place_from_file(v, "video", t3.id, 0)
    trm = ed3.trim_to_range(c3.id, 10, 50, mode="normal")
    assert trm["to"]["start"] == 10
    assert trm["to"]["end"] == 50
    assert ed3._find_clip(c3.id).timeline_duration_frames == 40

    # ripple trim
    ed4 = Editor.create(tmp_path / "p4.opm", fps=FPS, width=160, height=90)
    t4 = ed4.add_track("video")
    c4 = ed4.place_from_file(v, "video", t4.id, 0)
    m4 = ed4.project.media[0]
    c5 = ed4.add_clip(t4.id, m4.id, c4.end, 0, 30)
    old_c5 = ed4._find_clip(c5.id).start
    ed4.trim_to_range(c4.id, 0, 30, mode="ripple")
    assert ed4._find_clip(c4.id).timeline_duration_frames == 30
    assert ed4._find_clip(c5.id).start == old_c5 - 30

    # auto_link_av
    ed5 = Editor.create(tmp_path / "p5.opm", fps=FPS, width=160, height=90)
    tv = ed5.add_track("video")
    cv = ed5.place_from_file(v, "video", tv.id, 0)
    d = ed5.detach_audio(cv.id, link=False)
    # unlink if any
    ed5.unlink_clips()
    al = ed5.auto_link_av()
    assert al["count"] >= 1
    assert ed5._find_clip(cv.id).link_group

    # meta batch
    ed5.set_clips_meta([cv.id], name="Hero", color="#3d5a80")
    assert ed5._find_clip(cv.id).name == "Hero"


def test_web_join_autolink(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "w.mp4"
    _vid(v, "navy", 1.5)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/split", json={"clip_id": cid, "at_frame": 15})
    assert r.status_code == 200, r.text
    # get two clip ids from timeline
    tv = client.get("/api/project/timeline").json()
    clips = tv["tracks"][0]["clips"]
    assert len(clips) >= 2
    r = client.post("/api/clips/join", json={
        "clip_id_a": clips[0]["id"], "clip_id_b": clips[1]["id"],
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/clips/speed", json={
        "clip_ids": [r.json()["clip_id"]], "speed": 1.5,
    })
    assert r.status_code == 200
    r = client.post("/api/auto_link_av", json={})
    assert r.status_code == 200
