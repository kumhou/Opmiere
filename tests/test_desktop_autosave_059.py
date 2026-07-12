"""Desktop autosave toggle (0.4.19)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_autosave_toggle():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    d0 = client.get("/api/dirty").json()
    assert "autosave" in d0
    assert d0["autosave"] is False

    on = client.post("/api/autosave", json={"enabled": True})
    assert on.status_code == 200
    assert on.json()["autosave"] is True

    d1 = client.get("/api/dirty").json()
    assert d1["autosave"] is True

    off = client.post("/api/autosave", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["autosave"] is False

    tl = client.get("/api/project/timeline").json()
    assert tl.get("autosave") is False
