"""0.2.9: match_frame, clips_at, set_clip_fades, relink_clip, detach web."""

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


def test_clips_at_and_match_frame(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "red", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    hits = ed.clips_at(5)
    assert hits["count"] >= 1
    assert hits["hits"][0]["clip_id"] == c.id
    m = ed.match_frame(clip_id=c.id, timeline_frame=5)
    assert m["clip_id"] == c.id
    assert m["src_frame"] == c.src_in + 5
    assert m["media_id"] == c.media
    m2 = ed.match_frame(timeline_frame=3)
    assert m2["clip_id"] == c.id


def test_set_clip_fades(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, "blue", 0.8)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    r = ed.set_clip_fades(c.id, fade_in_frames=5, fade_out_frames=8)
    assert r["fade_in_frames"] == 5
    assert r["fade_out_frames"] == 8
    g = ed.get_clip_fades(c.id)
    assert g == {"clip_id": c.id, "fade_in_frames": 5, "fade_out_frames": 8}
    fades = [e for e in ed._find_clip(c.id).effects if e.get("type") == "fade"]
    assert len(fades) == 2
    # replace clears previous
    ed.set_clip_fades(c.id, fade_in_frames=3, fade_out_frames=0)
    g2 = ed.get_clip_fades(c.id)
    assert g2["fade_in_frames"] == 3
    assert g2["fade_out_frames"] == 0
    tv = ed.timeline_view()
    clip_row = tv["tracks"][0]["clips"][0]
    assert clip_row["fade_in_frames"] == 3
    assert clip_row["fade_out_frames"] == 0
    out = tmp_path / "fade.mp4"
    written = ed.export(out, normalize_preset=None)
    assert Path(written).exists()
    ed.undo()
    assert ed.get_clip_fades(c.id)["fade_in_frames"] == 5


def test_relink_clip(tmp_path: Path):
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v1, "green", 0.5)
    _vid(v2, "yellow", 0.7)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v1, "video", tr.id, 0)
    m2 = ed.import_media(v2, "video")
    mid = m2.id
    old = c.media
    r = ed.relink_clip(c.id, mid, keep_source_range=True)
    assert r["media_id"] == mid
    assert ed._find_clip(c.id).media == mid
    assert ed._find_clip(c.id).media != old


def test_web_match_fades_detach(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v, "navy", 0.6)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/clips/at", json={"timeline_frame": 2})
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1
    r = client.post("/api/clip/match_frame", json={
        "clip_id": cid, "timeline_frame": 2,
    })
    assert r.status_code == 200, r.text
    assert r.json()["src_frame"] >= 0
    r = client.post("/api/clip/fades", json={
        "clip_id": cid, "fade_in_frames": 4, "fade_out_frames": 4,
    })
    assert r.status_code == 200, r.text
    assert r.json()["fade_in_frames"] == 4
    r = client.post("/api/clip/detach_audio", json={"clip_id": cid})
    assert r.status_code == 200, r.text
    assert r.json()["audio_clip_id"]
