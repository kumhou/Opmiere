"""0.2.8: freeze_frame and reverse_clip."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.8) -> None:
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


def test_freeze_frame(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    r = ed.freeze_frame(c.id, duration_frames=15)
    assert r["clip_id"] != c.id
    still = ed._find_clip(r["clip_id"])
    assert still.timeline_duration_frames == 15
    media = ed.project.media_by_id(still.media)
    assert media.kind == "image"
    assert (ed.bundle.media_dir / media.path).exists()
    # export with freeze after clip — may need contiguity
    if still.start != c.end:
        still.start = c.end
    ed.close_gaps(tr.id)
    out = tmp_path / "out.mp4"
    written = ed.export(out, normalize_preset=None)
    assert Path(written).exists()


def test_reverse_clip(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    old_media = c.media
    r = ed.reverse_clip(c.id, replace=True)
    assert r["replaced"] is True
    c2 = ed._find_clip(c.id)
    assert c2.media != old_media
    assert c2.src_in == 0
    assert c2.speed == 1.0
    out = tmp_path / "rev.mp4"
    written = ed.export(out, normalize_preset=None)
    assert Path(written).exists()


def test_web_freeze_reverse(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 0.5)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/clip/freeze", json={
        "clip_id": cid, "duration_frames": 10,
    })
    assert r.status_code == 200, r.text
    assert r.json()["clip_id"]
    r = client.post("/api/clip/reverse", json={"clip_id": cid, "replace": True})
    assert r.status_code == 200, r.text
    assert r.json()["replaced"] is True
