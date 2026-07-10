"""0.2.2: copy/paste/duplicate + work in/out export."""

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


def test_copy_paste_duplicate(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    ed.apply_effect(c.id, {"type": "gain", "db": -3})
    cp = ed.copy_clip(c.id)
    assert cp["copied"]
    pasted = ed.paste_clip(track_id=tr.id, start=c.end)
    assert pasted["start"] == c.end
    pclip = ed._find_clip(pasted["clip_id"])
    assert pclip.media == c.media
    assert any(e.get("type") == "gain" for e in pclip.effects)
    dup = ed.duplicate_clip(c.id)
    assert dup["clip_id"] != c.id
    assert len(tr.clips) >= 3 or len(ed.project.tracks[0].clips) >= 3


def test_in_out_and_export_work(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "blue", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    ed.set_in_point(time_seconds=0.1)
    ed.set_out_point(time_seconds=0.5)
    io = ed.get_in_out()
    assert io["ready"]
    out = tmp_path / "seg.mp4"
    r = ed.export_work_area(out, normalize_preset=None, run_delivery_check=False)
    assert "path" in r
    assert Path(r["path"]).exists()
    assert Path(r["path"]).stat().st_size > 200


def test_web_clipboard_inout(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 0.7)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    assert client.post("/api/clip/copy", json={"clip_id": cid}).status_code == 200
    r = client.post("/api/clip/paste", json={"playhead_frame": 20})
    assert r.status_code == 200, r.text
    assert r.json()["clip_id"]
    r = client.post("/api/in_out/in", json={"time_seconds": 0.05})
    assert r.status_code == 200
    r = client.post("/api/in_out/out", json={"time_seconds": 0.4})
    assert r.json()["ready"] is True
