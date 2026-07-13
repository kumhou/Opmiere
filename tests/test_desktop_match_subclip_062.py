"""Desktop match-frame, subclip, markers-from-cuts (0.4.22)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_match_frame_subclip_markers_from_cuts():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    track = tl["tracks"][0]
    cid = track["clips"][0]["id"]
    tid = track["id"]
    n0 = sum(len(t["clips"]) for t in tl["tracks"])

    mf = client.post(
        "/api/clip/match_frame",
        json={"timeline_frame": 10, "clip_id": cid},
    )
    assert mf.status_code == 200
    body = mf.json()
    assert body.get("clip_id") == cid
    assert body.get("src_frame") is not None

    sc = client.post(
        "/api/clip/subclip",
        json={
            "clip_id": cid,
            "timeline_start": 4,
            "timeline_end": 16,
            "place": "after",
            "name": "sc062",
        },
    )
    assert sc.status_code == 200
    placed = sc.json()
    assert placed.get("placed") or placed.get("clip_id")
    if placed.get("timeline"):
        n1 = sum(len(t["clips"]) for t in placed["timeline"]["tracks"])
        assert n1 == n0 + 1

    mk = client.post(
        "/api/markers/from_cuts",
        json={"track_id": tid, "label_prefix": "Cut", "color": "#ffb703"},
    )
    assert mk.status_code == 200
    assert int(mk.json().get("count") or 0) >= 1

    listed = client.get("/api/markers").json()
    assert listed["count"] >= 1

    clr = client.post("/api/markers/clear")
    assert clr.status_code == 200
    assert client.get("/api/markers").json()["count"] == 0
