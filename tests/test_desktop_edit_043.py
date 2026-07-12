"""Desktop timeline edit: clip move + undo via HTTP API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_desktop_move_clip_and_undo():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    tl = client.get("/api/project/timeline").json()
    assert tl["duration_frames"] > 0
    tracks = tl["tracks"]
    assert tracks
    clips = tracks[0]["clips"]
    assert len(clips) >= 2
    c1 = clips[1]
    cid = c1["id"]
    old_start = int(c1["start_frame"])
    new_start = old_start + 5

    r = client.post(
        "/api/clip/move",
        json={
            "clip_id": cid,
            "start_frame": new_start,
            "refresh_preview": False,
            "quick_preview": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["clip"]["start"] == new_start
    assert body["timeline"]["tracks"][0]["clips"][1]["start_frame"] == new_start

    r = client.post("/api/undo")
    assert r.status_code == 200
    und = r.json()
    assert und.get("ok") is True
    restored = und["timeline"]["tracks"][0]["clips"][1]["start_frame"]
    assert restored == old_start
