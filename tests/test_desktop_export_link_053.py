"""Desktop export_work + link/unlink + redo (0.4.13)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_export_work_link_redo():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    # without I/O → soft fail
    bad = client.post("/api/desktop/export_work")
    assert bad.status_code == 200
    assert bad.json()["ok"] is False

    client.post("/api/in_out/in", json={"frame": 0})
    client.post("/api/in_out/out", json={"frame": 24})
    good = client.post("/api/desktop/export_work")
    assert good.status_code == 200
    body = good.json()
    # export may soft-fail on environment, but should not 500
    if body.get("ok"):
        assert body.get("path")
        assert Path(body["path"]).exists()

    tl = client.get("/api/project/timeline").json()
    tracks = tl["tracks"]
    # need two clips — demo has 2 on V1
    clips = tracks[0]["clips"]
    assert len(clips) >= 2
    ids = [clips[0]["id"], clips[1]["id"]]
    link = client.post("/api/clips/link", json={"clip_ids": ids})
    assert link.status_code == 200
    linked = link.json()["timeline"]["tracks"][0]["clips"]
    g0 = next(c for c in linked if c["id"] == ids[0]).get("link_group")
    g1 = next(c for c in linked if c["id"] == ids[1]).get("link_group")
    assert g0 and g0 == g1

    un = client.post("/api/clips/unlink", json={"clip_ids": ids})
    assert un.status_code == 200

    # undo/redo stack after link+unlink
    assert client.post("/api/undo").status_code == 200
    assert client.post("/api/redo").status_code == 200
