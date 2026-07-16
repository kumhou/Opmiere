"""Desktop single-clip APIs, ripple_delete timeline, preview/build (0.4.57)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, color: str = "maroon") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", f"-i", f"color=c={color}:s=160x90:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_single_clip_and_ripple_delete():
    root = Path(tempfile.mkdtemp(prefix="opmiere_097_"))
    try:
        client = TestClient(app)
        bundle = root / "s.opm"
        assert client.post(
            "/api/project/create",
            json={
                "bundle_path": str(bundle),
                "fps": 30,
                "width": 160,
                "height": 90,
            },
        ).status_code == 200

        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, "maroon")
        _vid(b, "navy")
        assert client.post(
            "/api/place_batch",
            json={"paths": [str(a), str(b)], "sequential": True},
        ).status_code == 200

        tl = client.get("/api/project/timeline").json()
        clips = tl["tracks"][0]["clips"]
        assert len(clips) >= 2
        c0, c1 = clips[0]["id"], clips[1]["id"]

        assert client.post(
            "/api/clip/gain", json={"clip_id": c0, "db": -3.0}
        ).status_code == 200
        assert client.post(
            "/api/clip/mute", json={"clip_id": c0, "muted": True}
        ).status_code == 200
        assert client.post(
            "/api/clip/opacity", json={"clip_id": c0, "amount": 0.8}
        ).status_code == 200
        assert client.post(
            "/api/clip/speed", json={"clip_id": c0, "speed": 1.0}
        ).status_code == 200
        assert client.post(
            "/api/clip/fades",
            json={
                "clip_id": c0,
                "fade_in_frames": 2,
                "fade_out_frames": 2,
            },
        ).status_code == 200

        fx = client.post(
            "/api/clips/effect",
            json={
                "clip_ids": [c0],
                "effect": {
                    "type": "ken_burns",
                    "zoom_start": 1.0,
                    "zoom_end": 1.1,
                    "x_start": 0.5,
                    "y_start": 0.5,
                    "x_end": 0.5,
                    "y_end": 0.5,
                },
            },
        )
        assert fx.status_code == 200, fx.text

        # delete first clip with ripple — later clip should shift left
        rdel = client.post("/api/ripple_delete", json={"clip_id": c0})
        assert rdel.status_code == 200, rdel.text
        body = rdel.json()
        assert "timeline" in body
        assert body.get("deleted_id") == c0
        remaining = body["timeline"]["tracks"][0]["clips"]
        assert all(c["id"] != c0 for c in remaining)
        # c1 should still be present
        assert any(c["id"] == c1 for c in remaining)

        # force build proxy
        build = client.post(
            "/api/preview/build",
            json={"height": 120, "fps": 8, "force": True},
        )
        assert build.status_code == 200, build.text

        # export_work needs I/O
        client.post("/api/in_out/in", json={"frame": 0})
        client.post("/api/in_out/out", json={"frame": 10})
        out = root / "work.mp4"
        ew = client.post(
            "/api/export_work",
            json={
                "output_path": str(out),
                "normalize_preset": None,
                "run_delivery_check": False,
            },
        )
        assert ew.status_code == 200, ew.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_single_api_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/ripple_delete" in ts
    assert "/api/clip/gain" in ts
    assert "/api/clip/mute" in ts
    assert "/api/clip/opacity" in ts
    assert "/api/clip/speed" in ts
    assert "/api/clip/fades" in ts
    assert "/api/preview/build" in ts
    assert "/api/export_work" in ts
    assert 'data-fx="glow"' in (
        root / "ui-desktop" / "index.html"
    ).read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'data-fx="ken"' in html
