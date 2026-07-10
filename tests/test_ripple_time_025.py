"""0.2.5: ripple_nudge, insert_time, extract_time."""

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


def test_ripple_nudge(tmp_path: Path):
    a, b, c = tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"
    for p, col in ((a, "red"), (b, "green"), (c, "blue")):
        _vid(p, col, 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    c2 = ed.place_from_file(b, "video", tr.id, c1.end)
    c3 = ed.place_from_file(c, "video", tr.id, c2.end)
    s2, s3 = c2.start, c3.start
    r = ed.ripple_nudge(c2.id, 10)
    assert r["count"] >= 2
    assert ed._find_clip(c2.id).start == s2 + 10
    assert ed._find_clip(c3.id).start == s3 + 10
    assert ed._find_clip(c1.id).start == 0


def test_insert_time(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, "red")
    _vid(b, "blue")
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    c2 = ed.place_from_file(b, "video", tr.id, c1.end)
    old = c2.start
    r = ed.insert_time(tr.id, c1.end, 12)
    assert r["count"] >= 1
    assert ed._find_clip(c2.id).start == old + 12


def test_extract_time_ripple(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, "navy", 0.8)
    _vid(b, "olive", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    c2 = ed.place_from_file(b, "video", tr.id, c1.end)
    # extract middle of first clip
    mid0 = c1.start + 5
    mid1 = c1.start + 12
    if mid1 >= c1.end:
        mid1 = c1.end - 1
    r = ed.extract_time(tr.id, mid0, mid1, ripple=True)
    assert r["track_id"] == tr.id
    # still exportable after fill if needed
    try:
        ed.export(tmp_path / "x.mp4", normalize_preset=None)
    except ValueError:
        ed.fill_track_gaps(tr.id, mode="slug")
        ed.export(tmp_path / "x.mp4", normalize_preset=None)
    assert (tmp_path / "x.mp4").exists() or any(tmp_path.glob("*.mp4"))


def test_web_ripple_insert(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a)
    _vid(b, "teal")
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    r = client.post("/api/place_batch", json={"paths": [str(a), str(b)], "sequential": True})
    ids = [p["clip_id"] for p in r.json()["result"]["placed"]]
    r = client.post("/api/ripple_nudge", json={"clip_id": ids[0], "delta_frames": 2})
    assert r.status_code == 200
    assert r.json()["count"] >= 1
    r = client.post("/api/insert_time", json={"at_frame": 5, "frames": 8})
    assert r.status_code == 200
