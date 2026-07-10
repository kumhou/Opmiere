"""0.2.12: trim_to_playhead, clear_clip_effects, export presets."""

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


def test_trim_to_playhead_head_tail(tmp_path: Path):
    v = tmp_path / "v.mp4"
    v2 = tmp_path / "v2.mp4"
    _vid(v, "red", 1.0)
    _vid(v2, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    # second clip after for ripple check
    c2 = ed.place_from_file(v2, "video", tr.id, c.end)
    old_c2_start = c2.start
    # head ripple: playhead at 10
    r = ed.trim_to_playhead(c.id, 10, edge="head", mode="ripple")
    assert r["edge"] == "head"
    c_after = ed._find_clip(c.id)
    assert c_after.src_in == 10
    assert c_after.start == 0  # ripple keeps start
    # second clip pulled left by 10
    c2_after = ed._find_clip(c2.id)
    assert c2_after.start == old_c2_start - 10

    # fresh for tail
    ed2 = Editor.create(tmp_path / "p2.opm", fps=FPS, width=160, height=90)
    tr2 = ed2.add_track("video")
    c3 = ed2.place_from_file(v, "video", tr2.id, 0)
    r2 = ed2.trim_to_playhead(c3.id, 12, edge="tail", mode="normal")
    assert r2["edge"] == "tail"
    c3b = ed2._find_clip(c3.id)
    assert c3b.src_out == 12
    assert c3b.end == 12


def test_clear_clip_effects(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    ed.set_clip_opacity(c.id, 0.5)
    ed.set_clip_gain(c.id, -3.0)
    listed = ed.list_clip_effects(c.id)
    assert listed["count"] >= 2
    r = ed.clear_clip_effects(c.id, types=["opacity"])
    assert "opacity" in r["removed_types"]
    assert ed.get_clip_opacity(c.id) == 1.0
    assert ed.get_clip_gain_db(c.id) == -3.0
    r2 = ed.clear_clip_effects(c.id)
    assert r2["remaining_count"] == 0


def test_export_presets_list_and_draft(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "green", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    presets = ed.list_export_presets()
    ids = {p["id"] for p in presets["presets"]}
    assert "draft" in ids and "streaming" in ids
    out = tmp_path / "draft.mp4"
    r = ed.export_with_preset(out, preset="draft")
    assert Path(r["path"]).exists()
    assert r["preset"] == "draft"


def test_web_trim_clear_presets(tmp_path: Path):
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
    r = client.post("/api/clip/trim_playhead", json={
        "clip_id": cid, "playhead_frame": 8, "edge": "head", "mode": "ripple",
    })
    assert r.status_code == 200, r.text
    client.post("/api/clip/opacity", json={"clip_id": cid, "amount": 0.3})
    r = client.post("/api/clip/clear_effects", json={"clip_id": cid})
    assert r.status_code == 200, r.text
    assert r.json()["remaining_count"] == 0
    pr = client.get("/api/export/presets")
    assert pr.status_code == 200
    assert pr.json()["count"] >= 4
