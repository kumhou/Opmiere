"""0.2.3: track mute/solo/lock, clip mute, export respects flags."""

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
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_track_flags_and_lock(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    ed.set_track_muted(tr.id, True)
    assert ed.project.track_by_id(tr.id).muted
    ed.set_track_solo(tr.id, True)
    assert ed.project.track_by_id(tr.id).solo
    ed.set_track_locked(tr.id, True)
    try:
        ed.move_clip(c.id, 5)
        raised = False
    except ValueError:
        raised = True
    assert raised
    ed.set_track_locked(tr.id, False)
    ed.move_clip(c.id, 0)


def test_clip_mute_export(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    ed.set_clip_muted(c.id, True)
    assert ed._find_clip(c.id).muted
    out = tmp_path / "out.mp4"
    written = ed.export(out, normalize_preset=None)
    assert Path(written).exists()
    assert Path(written).stat().st_size > 200


def test_solo_excludes_other_audio(tmp_path: Path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    for p, f in ((a, 220), (b, 880)):
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"sine=frequency={f}:duration=0.4",
                "-c:a", "pcm_s16le", str(p),
            ],
            capture_output=True, text=True, check=True,
        )
    v = tmp_path / "v.mp4"
    _vid(v, "blue", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    vt = ed.add_track("video")
    ed.place_from_file(v, "video", vt.id, 0)
    t1 = ed.add_track("audio")
    t2 = ed.add_track("audio")
    ed.place_from_file(a, "audio", t1.id, 0)
    ed.place_from_file(b, "audio", t2.id, 0)
    ed.set_track_solo(t1.id, True)
    out = tmp_path / "solo.mp4"
    written = ed.export(out, normalize_preset=None)
    assert Path(written).exists()


def test_web_mute_solo(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    state = client.get("/api/project/state").json()
    tid = state["tracks"][0]["id"]
    r = client.post("/api/track/mute", json={"track_id": tid, "value": True})
    assert r.status_code == 200
    assert r.json()["muted"] is True
    r = client.post("/api/clip/mute", json={"clip_id": cid, "muted": True})
    assert r.status_code == 200
    assert r.json()["muted"] is True
    # unmute track so export has video
    client.post("/api/track/mute", json={"track_id": tid, "value": False})
