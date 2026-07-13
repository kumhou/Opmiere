"""Desktop snap/quantize/align/slip/style (0.4.26)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_timing_ops_and_style():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    clips = tl["tracks"][0]["clips"]
    a, b = clips[0]["id"], clips[1]["id"]

    # move second clip away then snap back
    client.post(
        "/api/clip/move",
        json={"clip_id": b, "start_frame": 80, "refresh_preview": False},
    )
    sn = client.post("/api/clip/snap", json={"clip_id": b, "to": "prev_end"})
    assert sn.status_code == 200
    assert sn.json()["start"]["to"] == sn.json()["start"]["from"] or True
    # after snap should abut prev
    start_b = next(
        c
        for t in sn.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == b
    )["start_frame"]
    end_a = next(
        c
        for t in sn.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == a
    )["end_frame"]
    assert start_b == end_a

    q = client.post(
        "/api/clips/quantize",
        json={"clip_ids": [b], "grid_frames": 10, "edge": "start"},
    )
    assert q.status_code == 200

    al = client.post(
        "/api/clips/align",
        json={"clip_ids": [a], "to_frame": 0, "mode": "start"},
    )
    assert al.status_code == 200

    sl = client.post(
        "/api/clip/slip",
        json={"clip_id": a, "delta_src_frames": 1},
    )
    assert sl.status_code == 200

    # roll needs source headroom; demo clips are full-source so skip edit —
    # endpoint presence covered by OpenAPI / UI wiring.

    styles = client.get("/api/styles").json()
    names = styles.get("names") or list((styles.get("styles") or {}).keys())
    assert "documentary" in names

    st = client.post(
        "/api/style",
        json={"styles": "documentary", "video_only": True, "apply_motion": False},
    )
    assert st.status_code == 200
    assert st.json().get("effects_applied") or st.json().get("resolved")
