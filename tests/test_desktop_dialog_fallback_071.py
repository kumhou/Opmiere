"""Desktop open/create project paths (0.4.31 dialog fallback path).

Native Tauri dialogs are UI-only; HTTP create/open remain the source of truth.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def test_create_open_project_paths():
    client = TestClient(app)
    root = Path(tempfile.mkdtemp(prefix="opmiere_071_"))
    try:
        path = root / "shell.opm"
        r = client.post(
            "/api/project/create",
            json={
                "bundle_path": str(path),
                "fps": 30,
                "width": 1920,
                "height": 1080,
            },
        )
        assert r.status_code == 200
        assert r.json().get("id")

        assert client.post("/api/track?kind=video").status_code == 200
        assert client.post("/api/track?kind=audio").status_code == 200
        assert client.post("/api/save").json()["saved"] is True

        r2 = client.post("/api/project/open", json={"bundle_path": str(path)})
        assert r2.status_code == 200
        tl = client.get("/api/project/timeline").json()
        assert len(tl["tracks"]) >= 2

        # export dir endpoint always available for shell
        d = client.get("/api/desktop/export_dir")
        assert d.status_code == 200
        assert d.json().get("path")
    finally:
        shutil.rmtree(root, ignore_errors=True)
