"""Desktop add-track + markers nav support (0.4.10)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_add_tracks_and_marker_frames():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    before = client.get("/api/project/timeline").json()
    n0 = len(before["tracks"])

    assert client.post("/api/track?kind=video").status_code == 200
    assert client.post("/api/track?kind=audio").status_code == 200
    after = client.get("/api/project/timeline").json()
    assert len(after["tracks"]) == n0 + 2
    kinds = [t["kind"] for t in after["tracks"]]
    assert "audio" in kinds

    client.post("/api/markers", json={"frame": 5, "label": "a"})
    client.post("/api/markers", json={"frame": 20, "label": "b"})
    ms = client.get("/api/markers").json()["markers"]
    frames = sorted(m["frame"] for m in ms)
    assert 5 in frames and 20 in frames
