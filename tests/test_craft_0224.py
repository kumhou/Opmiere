"""0.2.24: stagger, reverse_track, clear_transitions, fades, append, dup range."""

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


def test_stagger_reverse_fades_dup_append(tmp_path: Path):
    v = tmp_path / "x.mp4"
    _vid(v, "red", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v, "video", tr.id, 0)
    m = ed.project.media[0]
    c2 = ed.add_clip(tr.id, m.id, c1.end, 0, 15)
    c3 = ed.add_clip(tr.id, m.id, c2.end, 0, 15)

    # reverse
    rev = ed.reverse_track_order(tr.id)
    assert rev["order"][0] == c3.id
    assert ed._find_clip(rev["order"][0]).start == 0

    # stagger selection of three after re-pack - reverse already packed
    ids = [x["clip_id"] for x in ed.clips_on_track(tr.id)["clips"]]
    # reset starts to same for stagger demo
    with ed._mutate():
        for i, cid in enumerate(ids):
            ed._find_clip(cid).start = 0
    st = ed.stagger_clips(ids, 10)
    assert st["count"] == 3
    starts = sorted(ed._find_clip(i).start for i in ids)
    assert starts == [0, 10, 20]

    # fades
    fd = ed.set_clips_fades(ids[:1], fade_in_frames=3, fade_out_frames=3)
    assert fd["count"] == 1
    assert ed.get_clip_fades(ids[0])["fade_in_frames"] == 3

    # append
    ap = ed.append_media(m.id, tr.id, src_in=0, src_out=10, name="Tail")
    assert ed._find_clip(ap["clip_id"]).name == "Tail"

    # duplicate range first 20 frames of track
    # pack first
    ed.close_all_gaps()
    first = ed.clips_on_track(tr.id)["clips"][0]
    end = min(20, ed.duration_frames())
    if end > first["start"]:
        dr = ed.duplicate_range(first["start"], end, track_id=tr.id)
        assert dr["count"] >= 1


def test_clear_transitions(tmp_path: Path):
    v = tmp_path / "t.mp4"
    _vid(v, "blue", 2.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v, "video", tr.id, 0)
    m = ed.project.media[0]
    # second clip hard cut then add transition
    c2 = ed.add_clip(tr.id, m.id, c1.end, 0, 30)
    ed.add_transition(c2.id, "cross_dissolve", 10)
    assert ed._find_clip(c2.id).transition_in is not None
    r = ed.clear_transitions(track_id=tr.id)
    assert r["count"] >= 1
    assert ed._find_clip(c2.id).transition_in is None
    assert ed._find_clip(c2.id).start == ed._find_clip(c1.id).end


def test_web_reverse_stagger(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "w.mp4"
    _vid(v, "navy", 1.0)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p1 = client.post("/api/place", json={"path": str(v), "kind": "video"})
    assert p1.status_code == 200
    tv = client.get("/api/project/timeline").json()
    tid = tv["tracks"][0]["id"]
    mid = tv["tracks"][0]["clips"][0]["media_id"]
    client.post("/api/append_media", json={
        "media_id": mid, "track_id": tid, "src_in": 0, "src_out": 10,
    })
    r = client.post("/api/track/reverse_order", json={"track_id": tid})
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 2
