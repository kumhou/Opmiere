"""Desktop razor / save / place_media (0.4.7 shell ops via HTTP)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_razor_save_place_media():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    before = client.get("/api/project/timeline").json()
    tracks = before["tracks"]
    assert tracks
    v0 = tracks[0]
    assert v0["kind"] == "video"
    assert len(v0["clips"]) >= 2
    n0 = sum(len(t["clips"]) for t in tracks)

    # razor mid first clip (demo clips are 24f each starting at 0)
    r = client.post("/api/razor", json={"at_frame": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["split_count"] >= 1
    n1 = sum(len(t["clips"]) for t in body["timeline"]["tracks"])
    assert n1 > n0

    # save
    s = client.post("/api/save")
    assert s.status_code == 200
    assert s.json()["saved"] is True

    # place first media at playhead-ish frame on first video track
    media = client.get("/api/media").json()
    items = media.get("media") or media.get("items") or []
    assert items
    mid = items[0]["id"]
    tid = v0["id"]
    p = client.post(
        "/api/place_media",
        json={
            "media_id": mid,
            "track_id": tid,
            "start": 200,
            "mode": "insert",
        },
    )
    assert p.status_code == 200
    placed = p.json()
    assert placed.get("clip_id")
    n2 = sum(len(t["clips"]) for t in placed["timeline"]["tracks"])
    assert n2 == n1 + 1
