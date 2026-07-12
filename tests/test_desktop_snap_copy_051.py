"""Desktop snap_frames + copy/paste/duplicate (0.4.11)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_snap_frames_and_clipboard():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    tl = client.get("/api/project/timeline").json()
    snaps = tl.get("snap_frames") or []
    assert 0 in snaps
    assert len(snaps) >= 2
    # edges of demo clips
    assert any(f > 0 for f in snaps)

    cid = tl["tracks"][0]["clips"][0]["id"]
    n0 = sum(len(t["clips"]) for t in tl["tracks"])

    c = client.post("/api/clip/copy", json={"clip_id": cid})
    assert c.status_code == 200
    assert c.json().get("copied") is True

    tid = tl["tracks"][0]["id"]
    p = client.post(
        "/api/clip/paste",
        json={"track_id": tid, "playhead_frame": 100, "mode": "insert"},
    )
    assert p.status_code == 200
    n1 = sum(len(t["clips"]) for t in p.json()["timeline"]["tracks"])
    assert n1 == n0 + 1

    d = client.post("/api/clip/duplicate", json={"clip_id": cid})
    assert d.status_code == 200
    n2 = sum(len(t["clips"]) for t in d.json()["timeline"]["tracks"])
    assert n2 == n1 + 1

    # snap to prev_end on a later clip
    clips = d.json()["timeline"]["tracks"][0]["clips"]
    if len(clips) >= 2:
        last = clips[-1]["id"]
        s = client.post("/api/clip/snap", json={"clip_id": last, "to": "prev_end"})
        assert s.status_code == 200
        assert "start" in s.json()
