"""Craft/mix/delivery APIs smoke for 0.4.71+ surface."""

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
            "-f", "lavfi", "-i", "color=c=olive:s=160x90:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_craft_routes_smoke():
    root = Path(tempfile.mkdtemp(prefix="opmiere_102_"))
    try:
        client = TestClient(app)
        bundle = root / "c.opm"
        assert client.post(
            "/api/project/create",
            json={
                "bundle_path": str(bundle),
                "fps": 30,
                "width": 160,
                "height": 90,
            },
        ).status_code == 200
        v = root / "v.mp4"
        _vid(v)
        client.post("/api/place_batch", json={"paths": [str(v)], "sequential": True})
        media = client.get("/api/media").json()["media"]
        mid = media[0]["id"]
        tl = client.get("/api/project/timeline").json()
        cid = tl["tracks"][0]["clips"][0]["id"]

        assert client.get("/api/looks").status_code == 200
        assert client.get("/api/encode_status").status_code == 200
        assert client.get(f"/api/media/{mid}/clips").status_code == 200
        assert client.get(f"/api/media/{mid}/transcript").status_code == 200

        r = client.post("/api/suggest/fps", json={"paths": [str(v)]})
        assert r.status_code in (200, 400), r.text
        r = client.post("/api/suggest/resolution", json={"paths": [str(v)]})
        assert r.status_code in (200, 400), r.text
        r = client.post("/api/delivery/limits", json={"paths": [str(v)], "fps": 30})
        assert r.status_code in (200, 400), r.text

        r = client.post(
            "/api/clip/apply_silence",
            json={"clip_id": cid, "dry_run": True},
        )
        assert r.status_code in (200, 400), r.text

        r = client.post(
            "/api/clips/color_match",
            json={"reference_clip_id": cid, "clip_ids": [cid], "strength": 0.5},
        )
        assert r.status_code in (200, 400), r.text

        r = client.post(
            "/api/clip/offset_linked",
            json={"clip_id": cid, "delta_frames": 0, "kinds": ["audio"]},
        )
        assert r.status_code in (200, 400), r.text

        r = client.post(
            "/api/export/range",
            json={
                "start_seconds": 0.0,
                "end_seconds": 0.2,
                "normalize_preset": None,
                "run_delivery_check": False,
            },
        )
        assert r.status_code in (200, 400, 500), r.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_craft_handlers_exist():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    for name in (
        "showLooksUi",
        "showEncodeStatusUi",
        "detectBeatsUi",
        "suggestMixUi",
        "colorMatchUi",
        "applySilenceUi",
        "placeAfterUi",
        "suggestFpsResUi",
        "deliveryLimitsUi",
        "captionClipUi",
        "exportRangeIoUi",
        "previewRangeIoUi",
        "offsetLinkedUi",
        "analyzeAssetUi",
    ):
        assert name in ts, name
