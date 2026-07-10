"""0.1.7: place_batch, mix_view, ducking web APIs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _wav(path: Path, dur: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={dur}",
            "-c:a", "pcm_s16le", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_guess_and_place_batch(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    w = tmp_path / "vo.wav"
    _vid(a, "red")
    _vid(b, "blue")
    _wav(w)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    assert Editor.guess_media_kind(w) == "audio"
    assert Editor.guess_media_kind(a) == "video"

    r = ed.place_batch([a, b, w], sequential=True)
    assert r["placed_count"] == 3
    assert r["error_count"] == 0
    # two video clips sequential on base V
    vtracks = [t for t in ed.project.tracks if t.kind == "video"]
    atracks = [t for t in ed.project.tracks if t.kind == "audio"]
    assert len(vtracks) >= 1
    assert len(atracks) >= 1
    assert len(vtracks[0].clips) == 2
    assert vtracks[0].clips_in_order()[1].start == vtracks[0].clips_in_order()[0].end
    assert len(atracks[0].clips) == 1


def test_mix_view_and_duck(tmp_path: Path):
    w1 = tmp_path / "m.wav"
    w2 = tmp_path / "v.wav"
    _wav(w1)
    _wav(w2)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    music = ed.add_track("audio")
    vo = ed.add_track("audio")
    ed.place_from_file(w1, "audio", music.id, 0)
    c_vo = ed.place_from_file(w2, "audio", vo.id, 0)
    ed.set_clip_gain(c_vo.id, 3.0)
    ed.set_ducking(music.id, vo.id, threshold_db=-28, ratio=6)
    mix = ed.mix_view()
    assert mix["audio_track_count"] == 2
    assert len(mix["duck_edges"]) == 1
    assert mix["duck_edges"][0]["from"] == music.id
    assert mix["duck_edges"][0]["against"] == vo.id
    # gains visible
    gains = {
        c["clip_id"]: c["gain_db"]
        for t in mix["audio_tracks"] for c in t["clips"]
    }
    assert gains[c_vo.id] == 3.0
    tv = ed.timeline_view()
    assert "mix" in tv
    assert tv["tracks"]
    # duck on track in timeline
    mtrack = next(t for t in tv["tracks"] if t["id"] == music.id)
    assert mtrack.get("duck")


def test_web_batch_and_mix(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a)
    _vid(b)
    client = TestClient(app)
    bundle = tmp_path / "w.opm"
    assert client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    r = client.post("/api/place_batch", json={
        "paths": [str(a), str(b)], "sequential": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["result"]["placed_count"] == 2

    # audio tracks for duck
    w1 = tmp_path / "m.wav"
    w2 = tmp_path / "v.wav"
    _wav(w1)
    _wav(w2)
    client.post("/api/place", json={"path": str(w1), "kind": "audio"})
    client.post("/api/place", json={"path": str(w2), "kind": "audio"})
    mix = client.get("/api/mix").json()
    assert mix["audio_track_count"] >= 1
    # if only one audio track (both placed on first audio), add second
    # place_batch/place uses first existing audio track — may be one track with 2 clips
    # create second audio and move not available; set_ducking needs 2 tracks
    ed_state = client.get("/api/project/state").json()
    audio_ids = [t["id"] for t in ed_state["tracks"] if t["kind"] == "audio"]
    if len(audio_ids) < 2:
        # open editor via new track API
        r = client.post("/api/track?kind=audio")
        assert r.status_code == 200
        # re-place second wav won't split — just test mix endpoint
        mix = client.get("/api/mix").json()
        assert "audio_tracks" in mix
    else:
        r = client.post("/api/duck", json={
            "track_id": audio_ids[0],
            "against_track_id": audio_ids[1],
        })
        assert r.status_code == 200
        assert r.json()["mix"]["duck_edges"]
