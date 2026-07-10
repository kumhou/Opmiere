"""0.1.6: waveform peaks, clip gain, media thumbs, web APIs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.waveform import extract_waveform_peaks

FPS = 30


def _av(path: Path, seconds: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:size=320x180:duration={seconds}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_extract_waveform_peaks(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _av(v, 0.6)
    r = extract_waveform_peaks(v, num_peaks=50)
    assert r["has_audio"] is True
    assert r["num_peaks"] == 50
    assert len(r["peaks"]) == 50
    assert max(r["peaks"]) > 0


def test_set_clip_gain_and_timeline(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _av(v, 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    assert ed.get_clip_gain_db(c.id) == 0.0
    r = ed.set_clip_gain(c.id, -6.0)
    assert r["db"]["to"] == -6.0
    assert ed.get_clip_gain_db(c.id) == -6.0
    tv = ed.timeline_view()
    assert tv["tracks"][0]["clips"][0]["gain_db"] == -6.0
    ed.set_clip_gain(c.id, 0.0)
    assert ed.get_clip_gain_db(c.id) == 0.0


def test_waveform_cache_and_thumb(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _av(v, 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    media = ed.import_media(v, "video")
    w1 = ed.waveform_peaks(media_id=media.id, num_peaks=40)
    assert w1["cache_hit"] is False
    assert len(w1["peaks"]) == 40
    w2 = ed.waveform_peaks(media_id=media.id, num_peaks=40)
    assert w2["cache_hit"] is True
    th = ed.media_thumbnail(media.id, width=80)
    assert Path(th["path"]).exists()
    th2 = ed.media_thumbnail(media.id, width=80)
    assert th2["cache_hit"] is True


def test_web_gain_waveform_thumb(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "a.mp4"
    _av(v, 0.5)
    client = TestClient(app)
    bundle = tmp_path / "w.opm"
    assert client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 320, "height": 180,
    }).status_code == 200
    place = client.post("/api/place", json={"path": str(v), "kind": "video"})
    assert place.status_code == 200
    clip_id = place.json()["id"]
    media_id = client.get("/api/media").json()["media"][0]["id"]

    r = client.post("/api/clip/gain", json={"clip_id": clip_id, "db": -3})
    assert r.status_code == 200
    assert r.json()["gain"]["db"]["to"] == -3

    r = client.post("/api/waveform", json={"media_id": media_id, "num_peaks": 32})
    assert r.status_code == 200
    assert len(r.json()["peaks"]) == 32

    r = client.get(f"/api/media/{media_id}/thumb.jpg", params={"width": 64})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 50

    r = client.post("/api/close_gaps", json={})
    assert r.status_code == 200
