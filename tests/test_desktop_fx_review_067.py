"""Desktop FX clipboard + attributes + review/sheet (0.4.27)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_fx_clipboard_attrs_review_sheet():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    a = tl["tracks"][0]["clips"][0]["id"]
    b = tl["tracks"][0]["clips"][1]["id"]

    # seed effects via style
    st = client.post(
        "/api/style",
        json={
            "styles": "documentary",
            "clip_ids": [a],
            "video_only": True,
            "apply_motion": False,
        },
    )
    assert st.status_code == 200

    cp = client.post("/api/clip/copy_effects", json={"clip_id": a})
    assert cp.status_code == 200
    assert cp.json().get("copied") is True
    assert int(cp.json().get("count") or 0) >= 1

    pst = client.post(
        "/api/clip/paste_effects",
        json={"clip_id": b, "replace": True},
    )
    assert pst.status_code == 200

    fx = client.get(f"/api/clip/effects/{b}").json()
    assert int(fx.get("count") or 0) >= 1

    ca = client.post("/api/clip/copy_attributes", json={"clip_id": a})
    assert ca.status_code == 200
    assert ca.json().get("copied") is True

    pa = client.post(
        "/api/clip/paste_attributes",
        json={
            "clip_id": b,
            "speed": True,
            "position": True,
            "gain": True,
            "opacity": True,
            "fades": True,
        },
    )
    assert pa.status_code == 200

    rev = client.post("/api/review")
    assert rev.status_code == 200

    sheet = client.post("/api/sequence_sheet", json={"max_tiles": 6})
    assert sheet.status_code == 200
