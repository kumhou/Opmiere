"""Desktop clip color + speed + recent list (0.4.15)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_color_speed_recent():
    client = TestClient(app)
    colors = client.get("/api/clip/colors").json()["colors"]
    assert len(colors) >= 4
    assert all(c.startswith("#") for c in colors)

    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    cid = tl["tracks"][0]["clips"][0]["id"]
    hexc = colors[2]

    r = client.post("/api/clips/color", json={"clip_ids": [cid], "color": hexc})
    assert r.status_code == 200
    clip = next(
        c
        for t in r.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == cid
    )
    assert clip.get("color") == hexc

    cyc = client.post("/api/clips/color_cycle", json={"clip_ids": [cid]})
    assert cyc.status_code == 200

    sp = client.post("/api/clips/speed", json={"clip_ids": [cid], "speed": 2.0})
    assert sp.status_code == 200
    clip2 = next(
        c
        for t in sp.json()["timeline"]["tracks"]
        for c in t["clips"]
        if c["id"] == cid
    )
    assert float(clip2.get("speed") or 0) == 2.0

    recent = client.get("/api/recent?limit=8").json()
    assert "projects" in recent
