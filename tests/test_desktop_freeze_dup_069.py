"""Desktop freeze, match duration, duplicate range, prepare_export (0.4.29)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_freeze_match_dup_prepare():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    tid = tl["tracks"][0]["id"]
    a = tl["tracks"][0]["clips"][0]["id"]
    b = tl["tracks"][0]["clips"][1]["id"]
    n0 = sum(len(t["clips"]) for t in tl["tracks"])

    fr = client.post(
        "/api/clip/freeze",
        json={
            "clip_id": a,
            "at_timeline_frame": 6,
            "duration_frames": 10,
        },
    )
    assert fr.status_code == 200
    assert "timeline" in fr.json()
    n1 = sum(len(t["clips"]) for t in fr.json()["timeline"]["tracks"])
    assert n1 >= n0

    # rematch on fresh demo
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl2 = client.get("/api/project/timeline").json()
    a2, b2 = tl2["tracks"][0]["clips"][0]["id"], tl2["tracks"][0]["clips"][1]["id"]
    tid2 = tl2["tracks"][0]["id"]
    md = client.post(
        "/api/clip/match_duration",
        json={"clip_id": b2, "reference_clip_id": a2, "clamp": True},
    )
    assert md.status_code == 200

    client.post("/api/in_out/in", json={"frame": 0})
    client.post("/api/in_out/out", json={"frame": 12})
    dr = client.post(
        "/api/duplicate_range",
        json={
            "start_frame": 0,
            "end_frame": 12,
            "track_id": tid2,
            "dest_start": 100,
        },
    )
    assert dr.status_code == 200
    assert "timeline" in dr.json()

    pe = client.post("/api/prepare_export")
    assert pe.status_code == 200
