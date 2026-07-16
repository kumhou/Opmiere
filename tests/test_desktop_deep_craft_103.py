"""Deep craft APIs for 0.4.81+ (smoke)."""

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
            "-f", "lavfi", "-i", "color=c=teal:s=160x90:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_deep_craft_routes():
    root = Path(tempfile.mkdtemp(prefix="opmiere_103_"))
    try:
        client = TestClient(app)
        bundle = root / "d.opm"
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
        tl = client.get("/api/project/timeline").json()
        cid = tl["tracks"][0]["clips"][0]["id"]

        assert client.get(f"/api/clip/{cid}/gain").status_code == 200
        assert client.get(f"/api/clip/{cid}/opacity").status_code == 200

        r = client.post("/api/media/slug", json={"kind": "video", "place": False})
        assert r.status_code == 200, r.text

        r = client.post(
            "/api/clip/transition",
            json={
                "clip_id": cid,
                "transition_type": "cross_dissolve",
                "duration_frames": 6,
            },
        )
        assert r.status_code in (200, 400), r.text

        r = client.post(
            "/api/ripple_delete_range",
            json={"start_frame": 0, "end_frame": 5},
        )
        assert r.status_code in (200, 400), r.text

        client.post("/api/markers", json={"frame": 3, "label": "A"})
        r = client.post(
            "/api/markers/color_batch",
            json={"color": "#ff0000"},
        )
        assert r.status_code == 200, r.text

        r = client.post(
            "/api/prepare_for_export",
            json={
                "fill_video": True,
                "fill_audio": False,
                "clear_empty_tracks": True,
            },
        )
        assert r.status_code in (200, 400), r.text

        r = client.post(
            "/api/media/extract_frame",
            json={"path": str(v), "time_seconds": 0.1, "width": 80},
        )
        assert r.status_code in (200, 400), r.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_deep_handlers_exist():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    for name in (
        "enrichClipGainOpacity",
        "trimClipToIoUi",
        "slugMediaUi",
        "clipTransitionUi",
        "rippleDeleteRangeIoUi",
        "markersColorBatchUi",
        "mediaContactSheetUi",
        "roomToneSuggestUi",
        "separateStemsUi",
        "prepareForExportUi",
    ):
        assert name in ts, name
