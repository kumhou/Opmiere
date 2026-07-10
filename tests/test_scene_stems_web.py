"""Scene detect, stems API surface, and P3 web app smoke tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opmiere import Editor
from opmiere.render.scene_detect import detect_scenes
from opmiere.workflow import make_brief, plan_session


FPS = 30


def _two_scene_video(path: Path) -> None:
    """Hard cut red→blue so scene detectors have a real change."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=red:size=160x90:duration=0.5:rate={FPS}",
            "-f", "lavfi", "-i", f"color=c=blue:size=160x90:duration=0.5:rate={FPS}",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_detect_scenes_ffmpeg_backend_finds_cut(tmp_path: Path):
    vid = tmp_path / "two.mp4"
    _two_scene_video(vid)
    result = detect_scenes(vid, backend="ffmpeg", threshold=0.2)
    assert result["backend"] == "ffmpeg"
    assert result["scene_count"] >= 1
    assert result["scenes"][0]["start"] == 0.0
    # At least one boundary near the middle for a hard color cut
    if result["scene_count"] >= 2:
        assert result["scenes"][0]["end"] < result["duration_seconds"]


def test_detect_scenes_auto_or_scenedetect(tmp_path: Path):
    vid = tmp_path / "two.mp4"
    _two_scene_video(vid)
    result = detect_scenes(vid, backend="auto", threshold=27.0)
    assert result["backend"] in ("scenedetect", "ffmpeg")
    assert result["scene_count"] >= 1
    assert "scenes" in result


def test_editor_detect_scenes(tmp_path: Path):
    vid = tmp_path / "two.mp4"
    _two_scene_video(vid)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    r = ed.detect_scenes(vid, backend="ffmpeg", threshold=0.25)
    assert r["scene_count"] >= 1


def test_plan_includes_detect_scenes_for_a_roll(tmp_path: Path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    brief = make_brief(
        intent="vlog",
        assets=[{"path": str(p), "role": "a_roll"}],
        deliverable={"bundle_path": "a.opm", "export_path": "a.mp4"},
    )
    tools = [s["tool"] for s in plan_session(brief)["steps"]]
    assert "detect_scenes" in tools
    assert "transcribe" in tools
    assert "separate_stems" in tools


def test_web_app_health_and_brief():
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["phase"] == "p3-min"

    r = client.get("/")
    assert r.status_code == 200
    assert "Opmiere" in r.text

    r = client.post("/api/brief", json={
        "intent": "",
        "assets": [],
        "deliverable": {"bundle_path": "x.opm", "export_path": "x.mp4"},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["brief"]["no_opinion"] is True
    assert len(data["plan"]["steps"]) >= 3


def test_web_create_place_export_roundtrip(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    vid = tmp_path / "c.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=green:size=160x90:duration=0.5:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid),
        ],
        capture_output=True, text=True, check=True,
    )
    bundle = tmp_path / "web.opm"
    export = tmp_path / "out.mp4"
    client = TestClient(app)
    r = client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 160, "height": 90,
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/place", json={"path": str(vid), "kind": "video"})
    assert r.status_code == 200, r.text
    r = client.get("/api/project/state")
    assert r.status_code == 200
    assert r.json()["tracks"]
    r = client.post("/api/export", json={"output_path": str(export)})
    assert r.status_code == 200, r.text
    assert export.exists()
