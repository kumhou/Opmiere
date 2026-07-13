"""Desktop history + select-at-playhead + duration report (0.4.21)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_history_select_at_duration():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    h0 = client.get("/api/history").json()
    assert "can_undo" in h0
    assert "undo_depth" in h0
    depth0 = int(h0.get("undo_depth") or 0)

    # mutate → undo depth grows
    tl = client.get("/api/project/timeline").json()
    cid = tl["tracks"][0]["clips"][0]["id"]
    client.post("/api/clips/mute", json={"clip_ids": [cid], "muted": True})
    h1 = client.get("/api/history").json()
    assert h1["can_undo"] is True
    assert int(h1.get("undo_depth") or 0) >= depth0

    assert client.post("/api/undo").status_code == 200
    h2 = client.get("/api/history").json()
    assert h2["can_redo"] is True

    at = client.post("/api/clips/at", json={"timeline_frame": 10})
    assert at.status_code == 200
    body = at.json()
    assert body["count"] >= 1
    assert body["hits"][0]["clip_id"]

    at2 = client.post("/api/clips/at", json={"timeline_frame": 30})
    assert at2.status_code == 200
    assert at2.json()["count"] >= 1

    dr = client.get("/api/duration_report").json()
    assert dr["duration_frames"] > 0
    assert dr["track_count"] >= 1
    assert "duration_seconds" in dr
