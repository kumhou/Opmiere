"""Lightweight timeline preview proxy + frame_at."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _clip(path: Path, color: str = "blue", dur: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=320x180:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_frame_at_base_track(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _clip(a, "blue", 0.6)
    _clip(b, "red", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    ed.place_from_file(b, "video", tr.id, c1.end)
    out = tmp_path / "f.jpg"
    r = ed.frame_at(0.1, out, prefer_proxy=False, width=160)
    assert r["mode"] == "base_track"
    assert Path(r["path"]).exists()
    assert Path(r["path"]).stat().st_size > 0


def test_export_preview_and_proxy_frame(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "green", 0.8)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    proxy = tmp_path / "proxy.mp4"
    info = ed.export_preview(proxy, height=120, fps=8)
    assert Path(info["path"]).exists()
    assert info["height"] and info["height"] <= 180
    frame = tmp_path / "p.jpg"
    r = ed.frame_at(0.2, frame, prefer_proxy=True, width=120)
    assert r["mode"] == "proxy"
    assert Path(r["path"]).exists()


def test_proxy_invalidated_after_mutate(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "blue", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    proxy = tmp_path / "px.mp4"
    ed.export_preview(proxy, height=120, fps=8)
    st = ed.preview_proxy_status()
    assert st["fresh"] is True
    # mutate timeline
    ed.apply_effect(
        ed.project.tracks[0].clips[0].id,
        {"type": "color", "brightness": 0.05, "contrast": 1.0, "saturation": 1.0},
    )
    st2 = ed.preview_proxy_status()
    assert st2["fresh"] is False
    frame = tmp_path / "stale.jpg"
    r = ed.frame_at(0.1, frame, prefer_proxy=True)
    assert r["mode"] == "base_track"
    assert "stale" in (r.get("agent_note") or "").lower()


def test_web_preview_endpoints(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _clip(v, "white", 0.5)
    client = TestClient(app)
    bundle = tmp_path / "w.opm"
    r = client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 320, "height": 180,
    })
    assert r.status_code == 200
    r = client.post("/api/place", json={"path": str(v), "kind": "video"})
    assert r.status_code == 200
    r = client.get("/api/preview/frame.jpg", params={"t": 0.1, "width": 160})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 100
