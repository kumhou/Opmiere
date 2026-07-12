"""snap_frames available for edit-point nav (0.4.14)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_snap_frames_are_sorted_unique_edges():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    tl = client.get("/api/project/timeline").json()
    snaps = tl.get("snap_frames") or []
    assert snaps == sorted(snaps)
    assert snaps[0] == 0
    # at least clip edges from 2×24f clips
    assert len(snaps) >= 3
    # no duplicates
    assert len(snaps) == len(set(snaps))

    # razor creates new snap edge
    client.post("/api/razor", json={"at_frame": 12})
    snaps2 = client.get("/api/project/timeline").json()["snap_frames"]
    assert 12 in snaps2
