"""Desktop crop + PiP position (0.4.49)."""

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
            "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=0.4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_crop_and_position_api():
    root = Path(tempfile.mkdtemp(prefix="opmiere_089_"))
    try:
        client = TestClient(app)
        bundle = root / "z.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 1920, "height": 1080},
        ).status_code == 200
        v = root / "v.mp4"
        _vid(v)
        assert client.post(
            "/api/place_batch", json={"paths": [str(v)], "sequential": True}
        ).status_code == 200
        cid = client.get("/api/project/timeline").json()["tracks"][0]["clips"][0]["id"]
        r = client.post(
            "/api/clip/crop", json={"clip_id": cid, "width": 1080, "height": 1080}
        )
        assert r.status_code == 200, r.text
        r2 = client.post(
            "/api/clip/position",
            json={"clip_id": cid, "x": 0.6, "y": 0.05, "scale": 0.3},
        )
        assert r2.status_code == 200, r2.text
        r3 = client.post("/api/clip/position/clear", json={"clip_id": cid})
        assert r3.status_code == 200, r3.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_crop_pip_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "cropSelection" in ts
    assert "positionSelection" in ts
    assert "/api/clip/crop" in ts
    assert "/api/clip/position" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-crop-sq"' in html
    assert 'id="btn-pip-tr"' in html
