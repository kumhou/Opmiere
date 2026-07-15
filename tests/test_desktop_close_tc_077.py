"""Project close + timecode jump (0.4.37)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=160x90:d=0.4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_project_close_api():
    root = Path(tempfile.mkdtemp(prefix="opmiere_077_"))
    try:
        client = TestClient(app)
        bundle = root / "c.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        assert client.get("/api/health").json()["project_open"] is True

        # close without save
        r = client.post("/api/project/close", json={"save": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["closed"] is True
        assert body["was_open"] is True
        assert body["project_open"] is False
        assert client.get("/api/health").json()["project_open"] is False

        # second close is no-op
        r2 = client.post("/api/project/close", json={})
        assert r2.status_code == 200
        assert r2.json()["was_open"] is False

        # reopen then close with save
        assert client.post("/api/project/open", json={"bundle_path": str(bundle)}).status_code == 200
        assert client.post("/api/track?kind=video").status_code == 200
        r3 = client.post("/api/project/close", json={"save": True})
        assert r3.status_code == 200
        assert r3.json()["saved"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tc_parse_roundtrip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_077tc_"))
    try:
        client = TestClient(app)
        bundle = root / "t.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        r = client.post("/api/tc/parse", json={"tc": "00:00:01:15"})
        assert r.status_code == 200
        assert r.json()["frame"] == 45  # 1*30 + 15
        client.post("/api/project/close", json={})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_shell_close_and_tc_wiring():
    root = Path(__file__).resolve().parents[1]
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-close"' in html
    assert 'id="tc"' in html
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "closeProject" in ts
    assert "jumpToTimecode" in ts
    assert "parseTcToSeconds" in ts
    assert "/api/project/close" in ts
