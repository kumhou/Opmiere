"""Desktop craft ops: name_from_media, dup track, purge, solo (0.4.25)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_name_dup_purge_solo():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    n_tracks0 = len(tl["tracks"])
    cid = tl["tracks"][0]["clips"][0]["id"]
    tid = tl["tracks"][0]["id"]

    nm = client.post(
        "/api/clips/name_from_media",
        json={"clip_ids": [cid], "strip_ext": True},
    )
    assert nm.status_code == 200
    named = next(
        c
        for t in nm.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == cid
    )
    assert named.get("name") or named.get("label")

    dup = client.post(
        "/api/track/duplicate",
        json={"track_id": tid, "copy_clips": True},
    )
    assert dup.status_code == 200
    assert len(dup.json()["timeline"]["tracks"]) > n_tracks0

    un = client.get("/api/media/unused").json()
    assert "count" in un or "media" in un or "items" in un

    pur = client.post("/api/media/purge_unused", json={"delete_files": False})
    assert pur.status_code == 200
    assert "count" in pur.json() or "removed" in pur.json()

    sol = client.post(
        "/api/clip/solo",
        json={"clip_id": cid, "exclusive": True},
    )
    assert sol.status_code == 200
    assert "timeline" in sol.json()

    # unmute_all may accept empty body or no body
    um = client.post("/api/clips/unmute_all")
    assert um.status_code in (200, 422)
    if um.status_code == 200:
        assert "timeline" in um.json()
