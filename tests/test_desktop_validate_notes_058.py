"""Desktop validate + project notes (0.4.18)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_validate_and_notes():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True

    v = client.get("/api/validate").json()
    assert "ok" in v
    assert "issues" in v

    n = client.post("/api/notes", json={"notes": "desktop 0.4.18 note"})
    assert n.status_code == 200
    g = client.get("/api/notes").json()
    text = g.get("notes") if isinstance(g, dict) else None
    if text is None and isinstance(g, dict):
        text = g.get("text") or g.get("value")
    # Editor may return {"notes": "..."} or bare string wrapper
    assert "desktop 0.4.18 note" in str(g)

    tl = client.get("/api/project/timeline").json()
    assert "desktop 0.4.18 note" in (tl.get("notes") or "")
    assert tl.get("bundle_path")
