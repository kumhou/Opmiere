"""Desktop slide/stretch/stagger/reverse (0.4.28)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_stretch_stagger_reverse():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    track = tl["tracks"][0]
    tid = track["id"]
    a, b = track["clips"][0]["id"], track["clips"][1]["id"]

    # stretch first clip shorter (safe for full-source demo)
    st = client.post(
        "/api/clip/stretch",
        json={"clip_id": a, "target_duration_frames": 18, "clamp": True},
    )
    assert st.status_code == 200
    dur = next(
        c
        for t in st.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == a
    )["duration_frames"]
    assert dur == 18

    # re-demo then stagger
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl2 = client.get("/api/project/timeline").json()
    a2, b2 = tl2["tracks"][0]["clips"][0]["id"], tl2["tracks"][0]["clips"][1]["id"]
    tid2 = tl2["tracks"][0]["id"]
    sg = client.post(
        "/api/clips/stagger",
        json={"clip_ids": [a2, b2], "offset_frames": 6},
    )
    assert sg.status_code == 200

    rev = client.post(
        "/api/track/reverse_order",
        json={"track_id": tid2, "pack_from": 0},
    )
    assert rev.status_code == 200
    starts = [
        c["start_frame"]
        for c in rev.json()["timeline"]["tracks"][0]["clips"]
    ]
    assert starts == sorted(starts)

    # reverse clip media (may re-encode; just ensure endpoint works)
    cid = rev.json()["timeline"]["tracks"][0]["clips"][0]["id"]
    rc = client.post("/api/clip/reverse", json={"clip_id": cid, "replace": True})
    assert rc.status_code == 200


def test_fill_gaps_api():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tid = client.get("/api/project/timeline").json()["tracks"][0]["id"]
    # move second clip to create gap then fill
    b = client.get("/api/project/timeline").json()["tracks"][0]["clips"][1]["id"]
    client.post(
        "/api/clip/move",
        json={"clip_id": b, "start_frame": 60, "refresh_preview": False},
    )
    fg = client.post("/api/fill_gaps", json={"track_id": tid, "mode": "slug"})
    assert fg.status_code == 200
    assert "timeline" in fg.json()
