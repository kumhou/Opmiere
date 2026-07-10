"""0.2.18: stabilize_clip, export_markers, copy/paste attributes."""

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


def test_stabilize_clip(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    old = c.media
    r = ed.stabilize_clip(c.id, replace=True, strength=0.5)
    assert r["replaced"] is True
    assert r["rx"] >= 16
    c2 = ed._find_clip(c.id)
    assert c2.media != old
    assert c2.src_in == 0
    media = ed.project.media_by_id(c2.media)
    assert (ed.bundle.media_dir / media.path).exists()


def test_export_markers_and_attributes(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "blue", 0.5)
    _vid(v2, "green", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    ed.add_marker(0, label="Start")
    ed.add_marker(60, label="Mid")
    yt = ed.export_markers(format="youtube")
    assert "0:00" in yt["body"]
    assert "Mid" in yt["body"]
    csv_path = tmp_path / "m.csv"
    csv = ed.export_markers(csv_path, format="csv")
    assert csv["path"]
    assert csv_path.exists()
    assert "frame,seconds" in csv_path.read_text(encoding="utf-8")

    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
    ed.set_speed(c1.id, 0.5)
    ed.set_clip_gain(c1.id, -6)
    ed.set_clip_opacity(c1.id, 0.7)
    ed.set_clip_fades(c1.id, fade_in_frames=3, fade_out_frames=3)
    ed.set_position(c1.id, 0.1, 0.2, 0.4)
    ed.copy_attributes(c1.id)
    r = ed.paste_attributes(c2.id)
    assert "speed" in r["applied"]
    assert abs(ed._find_clip(c2.id).speed - 0.5) < 1e-6
    assert ed.get_clip_gain_db(c2.id) == -6
    assert abs(ed.get_clip_opacity(c2.id) - 0.7) < 1e-6
    assert ed._find_clip(c2.id).position is not None


def test_web_stabilize_markers_attr(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 0.4)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/clip/stabilize", json={
        "clip_id": cid, "replace": True, "strength": 0.5,
    })
    assert r.status_code == 200, r.text
    assert r.json()["replaced"] is True
    client.post("/api/markers", json={"frame": 5, "label": "Hi"})
    m = client.post("/api/markers/export", json={"format": "youtube"})
    assert m.status_code == 200
    assert "Hi" in m.json()["body"]
    client.post("/api/clip/copy_attributes", json={"clip_id": cid})
    # second clip for paste
    v2 = tmp_path / "v2.mp4"
    _vid(v2, "teal", 0.4)
    p2 = client.post("/api/place", json={"path": str(v2), "kind": "video"})
    cid2 = p2.json()["id"]
    r = client.post("/api/clip/paste_attributes", json={"clip_id": cid2})
    assert r.status_code == 200, r.text
