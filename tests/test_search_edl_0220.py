"""0.2.20: describe/search clips, import markers, EDL, linked trim."""

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


def test_describe_search_edl_import(tmp_path: Path):
    v1 = tmp_path / "hero_shot.mp4"
    v2 = tmp_path / "broll.mp4"
    _vid(v1, "red", 1.0)
    _vid(v2, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
    ed.set_clip_meta(c1.id, name="Hero")
    d = ed.describe_clip(c1.id)
    assert d["clip"]["name"] == "Hero"
    assert d["media"]["path"]
    assert d["track"]["kind"] == "video"
    s = ed.search_clips("hero")
    assert s["count"] >= 1
    assert any(h["clip_id"] == c1.id for h in s["hits"])
    s2 = ed.search_clips("broll")
    assert any(h["clip_id"] == c2.id for h in s2["hits"])

    edl = ed.export_edl(title="Test")
    assert edl["count"] == 2
    assert "TITLE:" in edl["body"]
    assert "V     C" in edl["body"]

    text = "0:00 Open\n0:02 Mid chapter\n"
    r = ed.import_markers(text, format="youtube")
    assert r["count"] >= 2
    assert ed.list_markers()["count"] >= 2


def test_trim_follow_links(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "green", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    d = ed.detach_audio(c.id, link=True)
    # head trim linked at 10
    r = ed.trim_to_playhead(c.id, 10, edge="head", mode="ripple", follow_links=True)
    assert r["follow_links"] is True
    assert r["count"] == 2
    assert ed._find_clip(c.id).src_in == 10
    assert ed._find_clip(d["audio_clip_id"]).src_in == 10


def test_web_search_import_edl(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "clip_alpha.mp4"
    _vid(v, "navy", 0.6)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.get(f"/api/clip/{cid}/describe")
    assert r.status_code == 200, r.text
    assert r.json()["clip"]["id"] == cid
    r = client.post("/api/clips/search", json={"query": "alpha"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1
    r = client.post("/api/markers/import", json={
        "text": "0:00 Start\n0:01 Beat\n",
        "format": "youtube",
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 2
    r = client.post("/api/export/edl", json={"title": "Web"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1
