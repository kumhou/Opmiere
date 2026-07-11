"""0.2.22: lift, split_at_markers, match_duration, cutlist, color, place_media."""

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


def test_lift_split_match_cutlist_color_place(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "red", 2.0)
    _vid(v2, "blue", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)  # 60f
    assert c1.timeline_duration_frames == 60

    # lift middle 10 frames → gap
    r = ed.lift(20, 30, track_id=tr.id)
    assert r["count"] == 1
    clips = ed.clips_on_track(tr.id)["clips"]
    assert len(clips) == 2
    assert clips[0]["end"] == 20
    assert clips[1]["start"] == 30

    # pack for marker split: place continuous again
    ed2 = Editor.create(tmp_path / "p2.opm", fps=FPS, width=160, height=90)
    tr2 = ed2.add_track("video")
    c = ed2.place_from_file(v1, "video", tr2.id, 0)
    ed2.add_marker(15, label="beat")
    ed2.add_marker(40, label="cut")
    sp = ed2.split_at_markers()
    assert sp["count"] == 2
    assert ed2.clips_on_track(tr2.id)["count"] == 3

    # match duration
    c_short = ed2.place_from_file(v2, "video", tr2.id, 200)
    ref = ed2.clips_on_track(tr2.id)["clips"][0]
    md = ed2.match_duration(c_short.id, ref["clip_id"])
    assert abs(
        ed2._find_clip(c_short.id).timeline_duration_frames
        - ed2._find_clip(ref["clip_id"]).timeline_duration_frames
    ) <= 1

    # color
    ids = [x["clip_id"] for x in ed2.clips_on_track(tr2.id)["clips"][:2]]
    ed2.set_clips_color(ids, "#ffb703")
    by = ed2.clips_by_color("#ffb703")
    assert by["count"] >= 2

    # cutlist
    cl = ed2.export_cutlist(format="csv")
    assert cl["count"] >= 3
    assert "start_tc" in cl["body"]
    assert "event" in cl["body"].splitlines()[0]

    # place_media overwrite (reuse media already in bin from place_from_file)
    m_id = ed2._find_clip(c_short.id).media
    first = ed2.clips_on_track(tr2.id)["clips"][0]
    pm = ed2.place_media(
        m_id, tr2.id, first["start"],
        src_in=0, src_out=10, mode="overwrite", name="OV",
    )
    assert pm["mode"] == "overwrite"
    assert ed2._find_clip(pm["clip_id"]).name == "OV"


def test_web_lift_cutlist(tmp_path: Path):
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
    assert p.status_code == 200
    r = client.post("/api/lift", json={"start_frame": 10, "end_frame": 20})
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1
    r = client.post("/api/export/cutlist", json={"format": "json"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1
    r = client.post("/api/markers", json={"frame": 5, "label": "m"})
    assert r.status_code == 200, r.text
    r2 = client.post("/api/split_at_markers", json={})
    assert r2.status_code == 200, r2.text
