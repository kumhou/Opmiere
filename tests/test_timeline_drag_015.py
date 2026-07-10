"""0.1.5: set_clip_layout, edge_trim, quick preview refresh, web drag APIs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _clip(path: Path, color: str = "blue", dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=320x180:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_set_clip_layout_move_and_trim(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "green", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    assert c.start == 0
    r = ed.set_clip_layout(c.id, start=10, src_in=5, src_out=25)
    assert r["to"]["start"] == 10
    assert r["to"]["src_in"] == 5
    assert r["to"]["src_out"] == 25
    clip = ed._find_clip(c.id)
    assert clip.timeline_duration_frames == 20


def test_edge_trim_left_keeps_right_edge(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "red", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    old_end = c.end
    # shorten head by 5 frames: start and src_in +5, end fixed
    ed.edge_trim(c.id, "left", 5, mode="normal")
    c2 = ed._find_clip(c.id)
    assert c2.start == 5
    assert c2.src_in == 5
    assert c2.end == old_end


def test_edge_trim_right(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "blue", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    full = c.src_out
    # shorten tail by 10
    ed.edge_trim(c.id, "right", -10, mode="normal")
    c2 = ed._find_clip(c.id)
    assert c2.src_out == full - 10
    assert c2.start == 0


def test_refresh_preview_proxy_quick_after_edit(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "white", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    p1 = ed.export_preview(tmp_path / "px.mp4", height=120, fps=8)
    assert p1["fresh"] is True or Path(p1["path"]).exists()
    assert ed.preview_proxy_status()["fresh"] is True
    # mutate with export-valid layout (base track still starts at 0)
    ed.edge_trim(c.id, "right", -5, mode="normal")
    assert ed.preview_proxy_status()["fresh"] is False
    r = ed.refresh_preview_proxy(quick=True)
    assert r.get("cache_hit") is False
    assert r.get("fresh") is True
    assert Path(r["path"]).exists()
    # second call hits cache
    r2 = ed.refresh_preview_proxy(quick=True)
    assert r2.get("cache_hit") is True


def test_web_clip_layout_api(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _clip(v, "cyan", 0.8)
    client = TestClient(app)
    bundle = tmp_path / "w.opm"
    assert client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 320, "height": 180,
    }).status_code == 200
    place = client.post("/api/place", json={"path": str(v), "kind": "video"})
    assert place.status_code == 200
    clip_id = place.json()["id"]
    # ensure a proxy exists so refresh path runs after layout
    client.post("/api/preview/ensure", json={"height": 120, "fps": 8})
    # Keep start=0 so base track stays exportable; trim head/tail only
    r = client.post("/api/clip/layout", json={
        "clip_id": clip_id,
        "start_frame": 0,
        "src_in": 2,
        "src_out": 20,
        "refresh_preview": True,
        "quick_preview": True,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["layout"]["to"]["src_in"] == 2
    assert data["layout"]["to"]["src_out"] == 20
    assert data["timeline"]["tracks"][0]["clips"][0]["src_in"] == 2
    assert data["preview"] is not None
    assert data["preview"].get("error") is None

    r = client.post("/api/clip/edge_trim", json={
        "clip_id": clip_id,
        "edge": "right",
        "delta_frames": -2,
        "refresh_preview": False,
    })
    assert r.status_code == 200
    r = client.post("/api/preview/refresh", json={"quick": True})
    assert r.status_code == 200
