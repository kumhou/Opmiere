"""Desktop close_gaps + lift/extract work area (0.4.23)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_close_gaps_and_lift_extract():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    tid = tl["tracks"][0]["id"]
    second = tl["tracks"][0]["clips"][1]["id"]

    # create a gap by moving second clip right
    m = client.post(
        "/api/clip/move",
        json={"clip_id": second, "start_frame": 60, "refresh_preview": False},
    )
    assert m.status_code == 200

    g = client.post("/api/close_gaps", json={"track_id": tid, "from_frame": 0})
    assert g.status_code == 200
    moved = g.json()["result"]["moved"]
    assert any(x["clip_id"] == second for x in moved)

    # I/O then lift
    client.post("/api/in_out/in", json={"frame": 0})
    client.post("/api/in_out/out", json={"frame": 12})
    lift = client.post(
        "/api/lift",
        json={"start_frame": 0, "end_frame": 12, "track_id": tid},
    )
    assert lift.status_code == 200
    assert "timeline" in lift.json()

    # re-demo for extract
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tid2 = client.get("/api/project/timeline").json()["tracks"][0]["id"]
    client.post("/api/in_out/in", json={"frame": 6})
    client.post("/api/in_out/out", json={"frame": 18})
    ex = client.post(
        "/api/extract_range",
        json={
            "start_frame": 6,
            "end_frame": 18,
            "track_id": tid2,
            "ripple": True,
        },
    )
    assert ex.status_code == 200
    assert "timeline" in ex.json()
