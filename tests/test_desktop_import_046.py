"""Desktop media import + ripple delete via HTTP."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _tiny_mp4(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", "color=c=purple:s=320x180:d=0.4:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True, capture_output=True,
    )


def test_upload_place_and_ripple_delete():
    client = TestClient(app)
    assert client.post("/api/desktop/demo_project").json()["ok"] is True
    before = client.get("/api/project/timeline").json()
    n0 = sum(len(t["clips"]) for t in before["tracks"])

    p = Path(tempfile.gettempdir()) / "opmiere_import046.mp4"
    _tiny_mp4(p)
    with p.open("rb") as f:
        r = client.post(
            "/api/upload_place",
            files=[("files", ("import046.mp4", f, "video/mp4"))],
        )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert len(body["errors"]) == 0
    after = body["timeline"]
    n1 = sum(len(t["clips"]) for t in after["tracks"])
    assert n1 == n0 + 1

    media = client.get("/api/media").json()
    assert media["count"] >= 3

    # delete first clip with ripple
    cid = after["tracks"][0]["clips"][0]["id"]
    r = client.post(
        "/api/clips/delete",
        json={"clip_ids": [cid], "ripple": True, "follow_links": False},
    )
    assert r.status_code == 200
    tl = r.json()["timeline"]
    assert all(c["id"] != cid for t in tl["tracks"] for c in t["clips"])
