"""Desktop Q/W trim, work-area from selection, ensure proxy (0.4.20)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_trim_playhead_and_work_area():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    clips = tl["tracks"][0]["clips"]
    assert len(clips) >= 2
    a, b = clips[0], clips[1]
    start = a.get("start_frame") or a.get("start") or 0
    dur = a.get("duration_frames") or 24
    mid = int(start + max(1, dur // 2))

    r = client.post(
        "/api/clip/trim_playhead",
        json={
            "clip_id": a["id"],
            "playhead_frame": mid,
            "edge": "tail",
            "mode": "normal",
            "follow_links": False,
        },
    )
    assert r.status_code == 200
    assert r.json().get("edge") in ("tail", "right")

    io = client.post(
        "/api/work_area/from_selection",
        json={"clip_ids": [a["id"], b["id"]]},
    )
    assert io.status_code == 200
    body = io.json()
    assert body.get("ready") is True
    assert body.get("in_frame") is not None
    assert body.get("out_frame") is not None

    one = client.post("/api/work_area/from_clip", json={"clip_id": b["id"]})
    assert one.status_code == 200
    assert one.json().get("ready") is True


def test_ensure_proxy_and_clear_effects():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    cid = tl["tracks"][0]["clips"][0]["id"]

    # paint some FX then clear
    client.post("/api/clips/gain", json={"clip_ids": [cid], "db": -3})
    client.post("/api/clips/opacity", json={"clip_ids": [cid], "amount": 0.8})
    clr = client.post("/api/clip/clear_effects", json={"clip_id": cid})
    assert clr.status_code == 200

    # fresh demo again for contiguous proxy build
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    ens = client.post("/api/preview/ensure", json={"height": 180, "fps": 8})
    assert ens.status_code == 200
    body = ens.json()
    assert body.get("path") or body.get("fresh") is not None
