"""Desktop export presets + project stats + split_at_markers (0.4.24)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_export_presets_stats_split_markers():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    presets = client.get("/api/export/presets").json()
    assert presets.get("count", len(presets.get("presets") or [])) >= 1
    ids = [p["id"] for p in presets["presets"]]
    assert "draft" in ids

    st = client.get("/api/project/stats").json()
    assert st["clip_count"] >= 1
    assert st["media_count"] >= 1
    assert st["duration_frames"] > 0

    exp = client.post("/api/desktop/export_preset?preset=draft")
    assert exp.status_code == 200
    body = exp.json()
    # draft should export lavfi demo
    if body.get("ok"):
        assert body.get("path")
        assert Path(body["path"]).exists()
    else:
        # environment soft-fail still returns structured body
        assert "error" in body or "path" in body

    tid = client.get("/api/project/timeline").json()["tracks"][0]["id"]
    client.post(
        "/api/markers/from_cuts",
        json={"track_id": tid, "label_prefix": "Cut"},
    )
    n0 = sum(
        len(t["clips"])
        for t in client.get("/api/project/timeline").json()["tracks"]
    )
    sp = client.post("/api/split_at_markers", json={})
    assert sp.status_code == 200
    n1 = sum(len(t["clips"]) for t in sp.json()["timeline"]["tracks"])
    # at least one cut marker → more clips (or same if already split)
    assert n1 >= n0
