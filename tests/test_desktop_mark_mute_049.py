"""Desktop markers + clip/track mute (0.4.9 shell ops via HTTP)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_markers_and_mute():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    # marker at frame 8
    r = client.post("/api/markers", json={"frame": 8, "label": "cut"})
    assert r.status_code == 200
    body = r.json()
    mid = body["marker"]["id"]
    assert body["markers"]
    listed = client.get("/api/markers").json()
    assert listed["count"] >= 1
    assert any(m["id"] == mid for m in listed["markers"])

    # mute first clip
    tl = client.get("/api/project/timeline").json()
    cid = tl["tracks"][0]["clips"][0]["id"]
    tid = tl["tracks"][0]["id"]
    m = client.post("/api/clips/mute", json={"clip_ids": [cid], "muted": True})
    assert m.status_code == 200
    clips = m.json()["timeline"]["tracks"][0]["clips"]
    muted_clip = next(c for c in clips if c["id"] == cid)
    assert muted_clip["muted"] is True

    # track mute + solo
    tm = client.post("/api/track/mute", json={"track_id": tid, "value": True})
    assert tm.status_code == 200
    tr = next(t for t in tm.json()["timeline"]["tracks"] if t["id"] == tid)
    assert tr["muted"] is True

    ts = client.post("/api/track/solo", json={"track_id": tid, "value": True})
    assert ts.status_code == 200
    tr2 = next(t for t in ts.json()["timeline"]["tracks"] if t["id"] == tid)
    assert tr2["solo"] is True

    # delete marker
    d = client.post("/api/markers/delete", json={"marker_id": mid})
    assert d.status_code == 200
    assert all(m["id"] != mid for m in d.json()["markers"])
