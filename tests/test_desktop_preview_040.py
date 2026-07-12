"""Desktop product shell APIs: demo project + program frame."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_desktop_demo_and_program_frame():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["project_open"] is False

    r = client.post("/api/desktop/demo_project")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("duration_frames", 0) > 0

    r = client.get("/api/health")
    assert r.json()["project_open"] is True

    r = client.get("/api/preview/interactive")
    assert r.status_code == 200
    assert "active_backend" in r.json()

    r = client.get(
        "/api/preview/frame.jpg",
        params={"t": 0.15, "width": 320, "engine": "auto"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 500

    r = client.post(
        "/api/preview/frame",
        json={"time_seconds": 0.3, "width": 320, "engine": "auto"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("path") or data.get("ok") is not False

    r = client.get("/api/project/timeline")
    assert r.status_code == 200
    tl = r.json()
    assert tl.get("duration_frames", 0) > 0
    assert tl.get("tracks")
