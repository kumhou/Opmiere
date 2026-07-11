"""0.2.32: browser upload_place + shell assets present."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app

FPS = 30


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=navy:size=160x90:duration=0.4:rate={FPS}",
            "-f", "lavfi", "-i", "sine=duration=0.4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_upload_place(tmp_path: Path):
    v = tmp_path / "drop.mp4"
    _vid(v)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "u.opm"),
        "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    with v.open("rb") as f:
        r = client.post(
            "/api/upload_place",
            files=[("files", ("drop.mp4", f, "video/mp4"))],
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["timeline"]["tracks"]


def test_shell_has_v4_chrome():
    html = Path(__file__).resolve().parents[1] / "src" / "opmiere" / "web" / "static" / "index.html"
    t = html.read_text(encoding="utf-8")
    assert 'id="dropZone"' in t
    assert 'id="btnFullscreen"' in t
    assert "UI shell v4" in t
    assert "--color-primary" in t
