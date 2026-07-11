"""0.2.21: fit_to_fill, replace_edit, import_edl, copy_to_track, rename, range."""

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


def test_fit_replace_copy_rename_range(tmp_path: Path):
    v1 = tmp_path / "shot_a.mp4"
    v2 = tmp_path / "shot_b.mp4"
    v3 = tmp_path / "alt.mp4"
    _vid(v1, "red", 1.0)
    _vid(v2, "blue", 1.0)
    _vid(v3, "yellow", 2.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, 45)  # gap after c1 if c1 ends at 30

    # place leaves c1 at full 30f; c2 at 45 → gap. Fit c1 to c2 start.
    r = ed.fit_to_fill(c1.id)
    assert r["end"]["to"] == c2.start
    assert abs(ed._find_clip(c1.id).end - c2.start) <= 1

    # range query
    rng = ed.clips_in_range(0, 100)
    assert rng["count"] >= 2
    ids = {h["clip_id"] for h in rng["clips"]}
    assert c1.id in ids and c2.id in ids

    # replace_edit stretch keeps duration
    m3 = ed.import_media(v3, "video")
    before_end = ed._find_clip(c1.id).end
    before_start = ed._find_clip(c1.id).start
    rep = ed.replace_edit(c1.id, m3.id, mode="stretch")
    assert rep["to"]["media"] == m3.id
    assert ed._find_clip(c1.id).start == before_start
    assert abs(ed._find_clip(c1.id).end - before_end) <= 1

    # copy to new track
    tr2 = ed.add_track("video")
    cp = ed.copy_to_track(c2.id, tr2.id)
    assert cp["clip_id"] != c2.id
    assert ed._find_clip(cp["clip_id"]).start == ed._find_clip(c2.id).start
    assert ed._find_clip_and_track(cp["clip_id"])[0].id == tr2.id

    # rename
    rn = ed.rename_clips("Shot {nn}", clip_ids=[c1.id, c2.id])
    assert rn["count"] == 2
    assert ed._find_clip(c1.id).name == "Shot 01"
    assert ed._find_clip(c2.id).name == "Shot 02"


def test_export_import_edl_roundtrip(tmp_path: Path):
    v1 = tmp_path / "hero_shot.mp4"
    v2 = tmp_path / "broll.mp4"
    _vid(v1, "red", 1.0)
    _vid(v2, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v1, "video", tr.id, 0)
    c2 = ed.place_from_file(v2, "video", tr.id, c1.end)
    ed.set_clip_meta(c1.id, name="Hero")
    edl = ed.export_edl(title="RT")
    assert edl["count"] == 2
    body = edl["body"]

    # clear track and re-import
    r = ed.import_edl(body, replace_track=True)
    assert r["count"] == 2
    assert r["skipped_count"] == 0
    clips = ed.clips_on_track(tr.id)["clips"]
    assert len(clips) == 2
    assert clips[0]["start"] == 0


def test_web_fit_rename_edl(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "alpha.mp4"
    v2 = tmp_path / "beta.mp4"
    _vid(v, "navy", 1.0)
    _vid(v2, "gray", 1.0)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p1 = client.post("/api/place", json={"path": str(v), "kind": "video"})
    assert p1.status_code == 200, p1.text
    cid = p1.json()["id"]
    p2 = client.post("/api/place", json={"path": str(v2), "kind": "video", "start": 45})
    assert p2.status_code == 200, p2.text

    r = client.post("/api/clip/fit_to_fill", json={"clip_id": cid})
    assert r.status_code == 200, r.text
    assert r.json()["end"]["to"] == 45

    r = client.post("/api/clips/rename", json={
        "pattern": "A{nn}", "clip_ids": [cid],
    })
    assert r.status_code == 200, r.text
    assert r.json()["renamed"][0]["to"] == "A01"

    edl = client.post("/api/export/edl", json={})
    assert edl.status_code == 200
    body = edl.json()["body"]
    r = client.post("/api/import/edl", json={"text": body, "replace_track": True})
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1

    r = client.post("/api/clips/in_range", json={"start_frame": 0, "end_frame": 200})
    assert r.status_code == 200
    assert r.json()["count"] >= 1
