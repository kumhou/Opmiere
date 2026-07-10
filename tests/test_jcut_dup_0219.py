"""0.2.19: split follow_links, J/L cut, duplicate_track, unused media, stats."""

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


def test_split_linked_and_jl_cut(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 10)
    d = ed.detach_audio(c.id, link=True)
    assert d["link_group"]
    # both cover frame 25
    r = ed.split_clip(c.id, 25, follow_links=True)
    assert r["count"] == 2
    assert r["right_link_group"]
    assert r["left_link_group"]
    # left video still linked to left audio
    left_v = ed._find_clip(c.id)
    assert left_v.link_group == r["left_link_group"]
    # J-cut on left video (audio leads by 5)
    ed.j_cut(c.id, 5)
    a_left = None
    for t in ed.project.tracks:
        for cl in t.clips:
            if cl.link_group == left_v.link_group and t.kind == "audio":
                a_left = cl
    assert a_left is not None
    assert a_left.start == left_v.start - 5


def test_duplicate_track_and_purge(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "blue", 0.4)
    _vid(v2, "green", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v1, "video", tr.id, 0)
    # import extra unused media
    unused = ed.import_media(v2, "video")
    assert ed.list_unused_media()["count"] >= 1
    r = ed.duplicate_track(tr.id, copy_clips=True, name="V copy")
    assert r["clip_count"] == 1
    assert ed.project.track_by_id(r["track_id"]).name == "V copy"
    # new clip has different id
    assert r["clips"][0]["from"] == c.id
    assert r["clips"][0]["to"] != c.id
    pur = ed.purge_unused_media(delete_files=False)
    assert unused.id in pur["removed"]
    st = ed.project_stats()
    assert st["clip_count"] >= 2
    assert st["track_count"] >= 2


def test_web_jcut_stats(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 0.8)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    d = client.post("/api/clip/detach_audio", json={"clip_id": cid})
    assert d.status_code == 200
    r = client.post("/api/split", json={
        "clip_id": cid, "at_frame": 10, "follow_links": True,
    })
    assert r.status_code == 200, r.text
    assert r.json().get("count", 0) >= 1 or r.json().get("first")
    # j_cut on original left piece
    r = client.post("/api/clip/j_cut", json={"clip_id": cid, "frames": 4})
    assert r.status_code == 200, r.text
    st = client.get("/api/project/stats")
    assert st.status_code == 200
    assert "clip_count" in st.json()
    tr = client.get("/api/tracks").json()["tracks"][0]["track_id"]
    r = client.post("/api/track/duplicate", json={"track_id": tr})
    assert r.status_code == 200, r.text
