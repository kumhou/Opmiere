"""Desktop insert/overwrite place mode (0.4.41)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, sec: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_place_overwrite_mode():
    root = Path(tempfile.mkdtemp(prefix="opmiere_081_"))
    try:
        client = TestClient(app)
        bundle = root / "p.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        assert client.post(
            "/api/place_batch", json={"paths": [str(a)], "sequential": True}
        ).status_code == 200
        media = client.get("/api/media").json()["media"]
        # place second via place_media overwrite at 0
        assert client.post(
            "/api/place_batch", json={"paths": [str(b)], "sequential": False}
        ).status_code == 200
        media = client.get("/api/media").json()["media"]
        mid_b = media[-1]["id"]
        tracks = client.get("/api/project/timeline").json()["tracks"]
        tid = tracks[0]["id"]
        r = client.post(
            "/api/place_media",
            json={
                "media_id": mid_b,
                "track_id": tid,
                "start": 0,
                "mode": "overwrite",
            },
        )
        assert r.status_code == 200, r.text
        clips = client.get("/api/project/timeline").json()["tracks"][0]["clips"]
        assert any(c.get("media_id") == mid_b for c in clips)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_overwrite_toggle_wiring():
    root = Path(__file__).resolve().parents[1]
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="chk-overwrite"' in html
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "currentEditMode" in ts
    assert 'mode: "overwrite"' in ts or "editMode" in ts
    assert 'k === "."' in ts
