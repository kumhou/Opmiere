"""Desktop clip search, stabilize, export dir, markers export (0.4.30)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_search_stabilize_export_dir():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    s = client.post("/api/clips/search", json={"query": "a"})
    assert s.status_code == 200
    body = s.json()
    assert body["count"] >= 1
    assert body["hits"][0]["clip_id"]

    # markers for export
    tid = client.get("/api/project/timeline").json()["tracks"][0]["id"]
    client.post("/api/markers", json={"frame": 12, "label": "chap"})
    mx = client.post("/api/markers/export", json={"format": "youtube"})
    assert mx.status_code == 200

    # stabilize first hit (demo is short; should return 200)
    cid = body["hits"][0]["clip_id"]
    st = client.post(
        "/api/clip/stabilize",
        json={"clip_id": cid, "replace": True, "strength": 1.0},
    )
    assert st.status_code == 200
    assert "timeline" in st.json()

    d = client.get("/api/desktop/export_dir")
    assert d.status_code == 200
    dj = d.json()
    assert dj.get("path")
    assert Path(dj["path"]).is_dir()

    desc = client.get(f"/api/clip/{cid}/describe")
    assert desc.status_code == 200
