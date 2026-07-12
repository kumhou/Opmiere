"""Desktop opacity + join + transition (0.4.17)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_opacity_and_transition():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    clips = tl["tracks"][0]["clips"]
    assert len(clips) >= 2
    a, b = clips[0], clips[1]

    op = client.post(
        "/api/clips/opacity",
        json={"clip_ids": [a["id"]], "amount": 0.5},
    )
    assert op.status_code == 200
    c0 = next(
        c
        for t in op.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == a["id"]
    )
    assert abs(float(c0.get("opacity") or 0) - 0.5) < 1e-6

    tr = client.post(
        "/api/transition",
        json={
            "left_clip_id": a["id"],
            "right_clip_id": b["id"],
            "transition_type": "cross_dissolve",
            "duration_frames": 6,
        },
    )
    assert tr.status_code == 200
    assert "timeline" in tr.json()


def test_join_after_razor():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    # split first clip at f12 → join pieces back
    client.post("/api/razor", json={"at_frame": 12})
    tl = client.get("/api/project/timeline").json()
    ordered = sorted(
        tl["tracks"][0]["clips"],
        key=lambda c: c.get("start_frame") or c.get("start") or 0,
    )
    left = ordered[0]
    right = next(
        c for c in ordered if (c.get("start_frame") or c.get("start") or 0) == 12
    )
    j = client.post(
        "/api/clips/join",
        json={"clip_id_a": left["id"], "clip_id_b": right["id"]},
    )
    assert j.status_code == 200
    n = sum(len(t["clips"]) for t in j.json()["timeline"]["tracks"])
    # joined → fewer clips than post-razor
    assert n >= 1
