"""Desktop agent workflow: brief, workflow, proxies, keymap (0.4.53)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_workflow_brief_keymap_dirty():
    client = TestClient(app)
    km = client.get("/api/help/keymap")
    assert km.status_code == 200
    assert km.json().get("shortcuts")

    wf = client.get("/api/workflow")
    assert wf.status_code == 200
    assert "workflow" in wf.json() or "version" in wf.json()

    br = client.post(
        "/api/brief",
        json={"intent": "short social cut", "assets": [], "constraints": {}, "deliverable": {}},
    )
    assert br.status_code == 200, br.text
    body = br.json()
    assert "brief" in body or "plan" in body


def test_agent_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "makeBriefUi" in ts
    assert "showWorkflow" in ts
    assert "ensureAllMediaProxies" in ts
    assert "enrichHelpFromKeymap" in ts
    assert "renameMarker" in ts
    assert "/api/brief" in ts
    assert "/api/workflow" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-brief"' in html
    assert 'id="btn-workflow"' in html
    assert 'id="btn-proxies-all"' in html
