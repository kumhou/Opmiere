"""Desktop open/create project via HTTP (0.4.8)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_create_open_project_with_tracks():
    client = TestClient(app)
    root = Path(tempfile.mkdtemp(prefix="opmiere_048_"))
    try:
        path = root / "shell.opm"
        r = client.post(
            "/api/project/create",
            json={"bundle_path": str(path), "fps": 30, "width": 1920, "height": 1080},
        )
        assert r.status_code == 200
        assert r.json().get("id")

        # shell seeds V + A after create
        assert client.post("/api/track?kind=video").status_code == 200
        assert client.post("/api/track?kind=audio").status_code == 200
        tl = client.get("/api/project/timeline").json()
        kinds = [t["kind"] for t in tl["tracks"]]
        assert kinds.count("video") >= 1
        assert kinds.count("audio") >= 1

        assert client.post("/api/save").json()["saved"] is True

        r2 = client.post("/api/project/open", json={"bundle_path": str(path)})
        assert r2.status_code == 200
        tl2 = client.get("/api/project/timeline").json()
        assert len(tl2["tracks"]) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)
