"""Desktop edge trim + cross-track move via HTTP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_edge_trim_and_cross_track():
    client = TestClient(app)
    demo = client.post("/api/desktop/demo_project").json()
    assert demo["ok"] is True
    assert len(demo.get("tracks") or []) >= 2

    tl = client.get("/api/project/timeline").json()
    vtracks = [t for t in tl["tracks"] if t["kind"] == "video"]
    assert len(vtracks) >= 2
    src_track = vtracks[0]
    dest_track = vtracks[1]
    assert len(src_track["clips"]) >= 2
    clip = src_track["clips"][0]
    cid = clip["id"]
    old_dur = int(clip["duration_frames"])

    # trim right edge shorter by 3 frames
    r = client.post(
        "/api/clip/edge_trim",
        json={
            "clip_id": cid,
            "edge": "right",
            "delta_frames": -3,
            "mode": "normal",
            "refresh_preview": False,
        },
    )
    assert r.status_code == 200
    trimmed = r.json()["timeline"]["tracks"][0]["clips"][0]
    assert int(trimmed["duration_frames"]) == old_dur - 3

    # move second clip to empty V track
    c2 = client.get("/api/project/timeline").json()["tracks"][0]["clips"][1]
    r = client.post(
        "/api/clip/move_to_track",
        json={
            "clip_id": c2["id"],
            "track_id": dest_track["id"],
            "start": int(c2["start_frame"]),
        },
    )
    assert r.status_code == 200
    tl2 = r.json()["timeline"]
    v0 = next(t for t in tl2["tracks"] if t["id"] == src_track["id"])
    v1 = next(t for t in tl2["tracks"] if t["id"] == dest_track["id"])
    assert all(c["id"] != c2["id"] for c in v0["clips"])
    assert any(c["id"] == c2["id"] for c in v1["clips"])

    # undo twice (reparent + trim)
    assert client.post("/api/undo").json().get("ok") is True
    assert client.post("/api/undo").json().get("ok") is True
