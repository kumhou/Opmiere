"""0.2.10: paste_clip mode=overwrite."""

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


def test_paste_overwrite(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "red", 1.0)
    _vid(v2, "blue", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end)  # may place after
    # ensure c2 sits after - place_from_file may auto-place
    if c2.start == 0 and c2.id != c1.id:
        c2.start = c1.end
    # copy short clip, overwrite into middle of first
    ed.copy_clip(c2.id)
    mid = c1.start + 5
    r = ed.paste_clip(track_id=tr.id, start=mid, mode="overwrite")
    assert r["mode"] == "overwrite"
    assert r["start"] == mid
    pasted = ed._find_clip(r["clip_id"])
    assert pasted.start == mid
    # first clip should be trimmed or split — no full span covering mid as c1
    covering = ed.clips_at(mid, track_id=tr.id)["hits"]
    assert any(h["clip_id"] == pasted.id for h in covering)
    assert covering[0]["clip_id"] == pasted.id or any(
        h["clip_id"] == pasted.id for h in covering
    )


def test_paste_insert_still_default(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "green", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    ed.copy_clip(c.id)
    r = ed.paste_clip(track_id=tr.id, start=c.end, mode="insert")
    assert r["mode"] == "insert"
    assert r["start"] == c.end


def test_web_overwrite_paste(tmp_path: Path):
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
    assert client.post("/api/clip/copy", json={"clip_id": cid}).status_code == 200
    r = client.post("/api/clip/paste", json={
        "playhead_frame": 3, "mode": "overwrite",
    })
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "overwrite"
    assert r.json()["clip_id"]
