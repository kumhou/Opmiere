"""0.2.26: work area helpers, markers from cuts, solo_clip, duration_report."""

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


def test_work_area_markers_solo_duration(tmp_path: Path):
    v = tmp_path / "z.mp4"
    _vid(v, "red", 1.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v, "video", tr.id, 0)
    c2 = ed.add_clip(tr.id, ed.project.media[0].id, c1.end, 0, 20)

    io = ed.set_work_area_from_clip(c1.id)
    assert io["in_frame"] == c1.start
    assert io["out_frame"] == c1.end
    io2 = ed.set_work_area_from_selection([c1.id, c2.id])
    assert io2["in_frame"] == c1.start
    assert io2["out_frame"] == c2.end

    mk = ed.markers_from_cuts(tr.id, include_start=True)
    assert mk["count"] >= 2
    ed.shift_markers(5)
    assert ed.list_markers()["markers"][0]["frame"] >= 5

    sol = ed.solo_clip(c1.id, exclusive=True)
    assert c1.id in sol["unmuted"]
    assert ed._find_clip(c2.id).muted is True
    ed.unmute_all_clips()
    assert ed._find_clip(c2.id).muted is False

    cy = ed.set_clips_color_cycle()
    assert cy["count"] >= 2

    dr = ed.duration_report()
    assert dr["duration_frames"] >= c2.end
    assert dr["track_count"] >= 1

    ed.clear_markers()
    assert ed.list_markers()["count"] == 0


def test_web_duration_work_area(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "w.mp4"
    _vid(v, "navy", 1.0)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/work_area/from_clip", json={"clip_id": cid})
    assert r.status_code == 200
    assert r.json()["ready"] is True
    r = client.get("/api/duration_report")
    assert r.status_code == 200
    assert r.json()["duration_frames"] > 0
