"""0.2.13: move_to_track, copy/paste effects, align_clips, slip/roll web."""

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


def test_move_align_fx(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "red", 0.6)
    _vid(v2, "blue", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    t0 = ed.add_track("video")
    t1 = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", t0.id, 10)
    c2 = ed.place_from_file(v2, "video", t0.id, 40)
    ed.move_to_track(c1.id, t1.id, start=5)
    assert ed._find_clip_and_track(c1.id)[0].id == t1.id
    assert ed._find_clip(c1.id).start == 5

    # align relative to 0 (min start was 5 → delta -5 → 0 and 35)
    ed.align_clips([c1.id, c2.id], to_frame=0, mode="relative")
    starts = sorted(ed._find_clip(x).start for x in (c1.id, c2.id))
    assert starts[0] == 0
    assert starts[1] == 35

    ed.set_clip_opacity(c1.id, 0.4)
    ed.set_clip_gain(c1.id, -2)
    cp = ed.copy_effects(c1.id)
    assert cp["count"] == 2
    ed.paste_effects(c2.id, replace=True)
    assert ed.get_clip_opacity(c2.id) == 0.4
    assert ed.get_clip_gain_db(c2.id) == -2
    h = ed.history_status()
    assert h["has_effects_clipboard"] is True


def test_slip_and_roll(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "green", 2.0)  # room to slip
    _vid(v2, "yellow", 2.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0, duration_frames=30)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end, duration_frames=30)
    old_in = c1.src_in
    ed.slip_clip(c1.id, 3)
    assert ed._find_clip(c1.id).src_in == old_in + 3
    # roll cut later by 5
    cut = ed._find_clip(c1.id).end
    assert ed._find_clip(c2.id).start == cut
    ed.roll_edit(c1.id, c2.id, 5)
    assert ed._find_clip(c1.id).end == cut + 5
    assert ed._find_clip(c2.id).start == cut + 5


def test_web_move_fx_slip(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "navy", 1.0)
    _vid(v2, "teal", 1.0)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    tr2 = client.post("/api/track", json={"kind": "video"})
    # add_track may take query param only — check
    if tr2.status_code != 200:
        tr2 = client.post("/api/track?kind=video")
    assert tr2.status_code == 200, tr2.text
    tid2 = tr2.json()["id"]
    p = client.post("/api/place", json={"path": str(v1), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/clip/slip", json={"clip_id": cid, "delta_src_frames": 2})
    assert r.status_code == 200, r.text
    client.post("/api/clip/opacity", json={"clip_id": cid, "amount": 0.5})
    assert client.post("/api/clip/copy_effects", json={"clip_id": cid}).status_code == 200
    p2 = client.post("/api/place", json={"path": str(v2), "kind": "video"})
    cid2 = p2.json()["id"]
    r = client.post("/api/clip/paste_effects", json={"clip_id": cid2, "replace": True})
    assert r.status_code == 200, r.text
    r = client.post("/api/clips/align", json={
        "clip_ids": [cid, cid2], "to_frame": 0, "mode": "relative",
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/clip/move_to_track", json={
        "clip_id": cid, "track_id": tid2,
    })
    assert r.status_code == 200, r.text
