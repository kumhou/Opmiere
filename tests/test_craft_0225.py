"""0.2.25: move_block, gain/opacity batch, validate, extract, xfade cuts, snap, cutlist RT."""

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


def test_block_gain_validate_extract_xfade_snap(tmp_path: Path):
    v = tmp_path / "s.mp4"
    _vid(v, "red", 2.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v, "video", tr.id, 0)
    m = ed.project.media[0]
    c2 = ed.add_clip(tr.id, m.id, c1.end, 0, 30)
    c3 = ed.add_clip(tr.id, m.id, c2.end, 0, 30)

    left0 = c2.start
    mb = ed.move_block([c2.id, c3.id], 100)
    assert mb["delta"] == 100 - left0
    assert ed._find_clip(c2.id).start == 100
    # re-pack for clean tests
    ed.close_gaps(tr.id)

    ids = [x["clip_id"] for x in ed.clips_on_track(tr.id)["clips"]]
    ed.set_clips_gain(ids, -3.0)
    assert ed.get_clip_gain_db(ids[0]) == -3.0
    ed.set_clips_opacity(ids[:1], 0.5)
    assert ed.get_clip_opacity(ids[0]) == 0.5

    # introduce gap for validate warn
    with ed._mutate():
        ed._find_clip(ids[-1]).start += 20
    vres = ed.validate_timeline(track_id=tr.id)
    assert vres["warn_count"] >= 1 or not vres["ok"] or vres["issue_count"] >= 1

    ed.close_gaps(tr.id)
    v2 = ed.validate_timeline(track_id=tr.id)
    assert v2["error_count"] == 0

    # extract middle
    clips = ed.clips_on_track(tr.id)["clips"]
    mid_start = clips[0]["end"] - 5
    mid_end = clips[0]["end"] + 5
    er = ed.extract_range(mid_start, mid_end, track_id=tr.id, ripple=True)
    assert er["count"] == 1

    # rebuild two hard cuts + xfade
    ed2 = Editor.create(tmp_path / "p2.opm", fps=FPS, width=160, height=90)
    t2 = ed2.add_track("video")
    a = ed2.place_from_file(v, "video", t2.id, 0)
    b = ed2.add_clip(t2.id, ed2.project.media[0].id, a.end, 0, 40)
    c = ed2.add_clip(t2.id, ed2.project.media[0].id, b.end, 0, 40)
    xf = ed2.apply_transitions_on_cuts(t2.id, duration_frames=8)
    assert xf["count"] >= 1
    assert ed2._find_clip(b.id).transition_in is not None

    # snap
    ed3 = Editor.create(tmp_path / "p3.opm", fps=FPS, width=160, height=90)
    t3 = ed3.add_track("video")
    x = ed3.place_from_file(v, "video", t3.id, 0)
    y = ed3.add_clip(t3.id, ed3.project.media[0].id, 80, 0, 20)
    sn = ed3.snap_clip(y.id, to="prev_end")
    assert sn["start"]["to"] == ed3._find_clip(x.id).end

    ed3.name_clips_from_media()
    assert ed3._find_clip(x.id).name == "s"

    ed3.quantize_clips([y.id], 10)
    assert ed3._find_clip(y.id).start % 10 == 0

    st = ed3.list_media_status()
    assert st["ok"] is True
    assert st["online_count"] >= 1


def test_cutlist_roundtrip(tmp_path: Path):
    v = tmp_path / "hero.mp4"
    _vid(v, "blue", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v, "video", tr.id, 0)
    ed.add_clip(tr.id, ed.project.media[0].id, c1.end, 0, 15)
    ed.set_clip_meta(c1.id, name="Hero")
    cl = ed.export_cutlist(format="csv")
    r = ed.import_cutlist(cl["body"], replace_track=True)
    assert r["count"] >= 2
    assert r["skipped_count"] == 0


def test_web_validate_block(tmp_path: Path):
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
    assert p.status_code == 200
    cid = p.json()["id"]
    r = client.get("/api/validate")
    assert r.status_code == 200
    assert "ok" in r.json()
    r = client.post("/api/clips/move_block", json={
        "clip_ids": [cid], "to_frame": 5,
    })
    assert r.status_code == 200, r.text
    r = client.post("/api/clips/gain", json={"clip_ids": [cid], "db": -1.5})
    assert r.status_code == 200
