"""0.2.4: multi-clip nudge, mute, delete/ripple."""

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
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_nudge_and_mute_many(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, "red")
    _vid(b, "blue")
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    c2 = ed.place_from_file(b, "video", tr.id, c1.end)
    r = ed.nudge_clips([c1.id, c2.id], 5)
    assert r["count"] == 2
    assert ed._find_clip(c1.id).start == 5
    ed.set_clips_muted([c1.id, c2.id], True)
    assert ed._find_clip(c1.id).muted and ed._find_clip(c2.id).muted


def test_delete_clips_ripple(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    c = tmp_path / "c.mp4"
    for p, col in ((a, "red"), (b, "green"), (c, "blue")):
        _vid(p, col, 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    c2 = ed.place_from_file(b, "video", tr.id, c1.end)
    c3 = ed.place_from_file(c, "video", tr.id, c2.end)
    end_before = c3.end
    ed.delete_clips([c2.id], ripple=True)
    assert c2.id not in {x.id for x in tr.clips}
    # c3 pulled left
    c3b = ed._find_clip(c3.id)
    assert c3b.start == c1.end
    assert ed.duration_frames() < end_before


def test_web_multi(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a)
    _vid(b, "orange")
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    r = client.post("/api/place_batch", json={"paths": [str(a), str(b)], "sequential": True})
    ids = [p["clip_id"] for p in r.json()["result"]["placed"]]
    r = client.post("/api/clips/nudge", json={"clip_ids": ids, "delta_frames": 3})
    assert r.status_code == 200
    assert r.json()["count"] == 2
    r = client.post("/api/clips/mute", json={"clip_ids": ids, "muted": True})
    assert r.status_code == 200
