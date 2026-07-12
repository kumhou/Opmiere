"""Desktop rename / gain / fades (0.4.16)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_meta_gain_fades():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    cid = tl["tracks"][0]["clips"][0]["id"]

    r = client.post(
        "/api/clips/meta",
        json={"clip_ids": [cid], "name": "hero"},
    )
    assert r.status_code == 200
    clip = next(
        c
        for t in r.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == cid
    )
    assert clip.get("name") == "hero"

    g = client.post("/api/clips/gain", json={"clip_ids": [cid], "db": -3.0})
    assert g.status_code == 200
    clip2 = next(
        c
        for t in g.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == cid
    )
    assert float(clip2.get("gain_db") or 0) == -3.0

    f = client.post(
        "/api/clips/fades",
        json={"clip_ids": [cid], "fade_in_frames": 6, "fade_out_frames": 12},
    )
    assert f.status_code == 200
    clip3 = next(
        c
        for t in f.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == cid
    )
    assert int(clip3.get("fade_in_frames") or 0) == 6
    assert int(clip3.get("fade_out_frames") or 0) == 12
