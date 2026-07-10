"""0.2.11: opacity, make_subclip, history_status, update_marker."""

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


def test_opacity_and_history(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    h0 = ed.history_status()
    assert h0["can_undo"] is True  # place mutated
    assert h0["dirty"] is True
    r = ed.set_clip_opacity(c.id, 0.4)
    assert r["opacity"]["to"] == 0.4
    assert ed.get_clip_opacity(c.id) == 0.4
    tv = ed.timeline_view()
    assert abs(tv["tracks"][0]["clips"][0]["opacity"] - 0.4) < 1e-6
    # export with opacity on base (alpha → black pad)
    out = tmp_path / "op.mp4"
    written = ed.export(out, normalize_preset=None)
    assert Path(written).exists()
    ed.set_clip_opacity(c.id, 1.0)
    assert ed.get_clip_opacity(c.id) == 1.0
    assert not any(e.get("type") == "opacity" for e in ed._find_clip(c.id).effects)


def test_make_subclip_work_area(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "blue", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    ed.set_in_point(5)
    ed.set_out_point(15)
    r = ed.make_subclip(c.id, use_work_area=True, place="after")
    assert r["placed"] is True
    sub = ed._find_clip(r["clip_id"])
    assert sub.start == c.end
    assert sub.src_in == 5
    assert sub.src_out == 15
    # clipboard mode
    r2 = ed.make_subclip(c.id, timeline_start=2, timeline_end=8, place="clipboard")
    assert r2["clipboard"] is True
    assert ed._clipboard is not None


def test_update_marker(tmp_path: Path):
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    m = ed.add_marker(10, label="a", color="#ff0000")
    mid = m["id"]
    u = ed.update_marker(mid, label="b", color="#00ff00", frame=20)
    assert u["label"] == "b"
    assert u["frame"] == 20
    assert ed.list_markers()["markers"][0]["label"] == "b"


def test_web_opacity_subclip_history(tmp_path: Path):
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
    r = client.post("/api/clip/opacity", json={"clip_id": cid, "amount": 0.5})
    assert r.status_code == 200, r.text
    assert r.json()["opacity"]["to"] == 0.5
    assert client.post("/api/in_out/in", json={"frame": 2}).status_code == 200
    assert client.post("/api/in_out/out", json={"frame": 10}).status_code == 200
    r = client.post("/api/clip/subclip", json={
        "clip_id": cid, "use_work_area": True, "place": "after",
    })
    assert r.status_code == 200, r.text
    assert r.json().get("clip_id")
    h = client.get("/api/history")
    assert h.status_code == 200
    assert "undo_depth" in h.json()
    m = client.post("/api/markers", json={"frame": 3, "label": "x"})
    mid = m.json()["marker"]["id"]
    u = client.post("/api/markers/update", json={
        "marker_id": mid, "label": "y", "frame": 6,
    })
    assert u.status_code == 200, u.text
    assert u.json()["marker"]["label"] == "y"
