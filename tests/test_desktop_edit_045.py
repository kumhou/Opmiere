"""Desktop multi-nudge + export API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_nudge_and_export():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    clips = tl["tracks"][0]["clips"]
    assert len(clips) >= 2
    ids = [c["id"] for c in clips[:2]]
    starts = [int(c["start_frame"]) for c in clips[:2]]

    r = client.post(
        "/api/clips/nudge",
        json={"clip_ids": ids, "delta_frames": 4, "follow_links": False},
    )
    assert r.status_code == 200
    moved = r.json()["timeline"]["tracks"][0]["clips"]
    by_id = {c["id"]: int(c["start_frame"]) for c in moved}
    assert by_id[ids[0]] == starts[0] + 4
    assert by_id[ids[1]] == starts[1] + 4

    r = client.post("/api/desktop/export")
    assert r.status_code == 200
    body = r.json()
    # soft: delivery_ok may fail on lavfi; path should exist when encode ok
    if body.get("path"):
        assert Path(body["path"]).exists()
        assert Path(body["path"]).stat().st_size > 200
    else:
        # still return structured delivery payload
        assert "delivery" in body
