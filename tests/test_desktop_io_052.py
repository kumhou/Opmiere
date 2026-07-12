"""Desktop work In/Out points (0.4.12)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_work_in_out():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    r = client.post("/api/in_out/in", json={"frame": 6})
    assert r.status_code == 200
    assert r.json()["in_frame"] == 6

    r = client.post("/api/in_out/out", json={"frame": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["out_frame"] == 30
    assert body["ready"] is True
    assert body["duration_frames"] == 24

    g = client.get("/api/in_out").json()
    assert g["in_frame"] == 6 and g["out_frame"] == 30

    tl = client.get("/api/project/timeline").json()
    io = tl.get("work_in_out") or {}
    assert io.get("in_frame") == 6
    assert io.get("out_frame") == 30

    c = client.post("/api/in_out/clear")
    assert c.status_code == 200
    assert c.json()["in_frame"] is None
    assert c.json()["out_frame"] is None
