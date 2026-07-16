"""Desktop clip/layout, clip/meta, fades, OpenShot plan (0.4.56)."""

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
            "-f", "lavfi", "-i", "color=c=olive:s=160x90:d=0.8",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_layout_meta_fades_os_plan():
    root = Path(tempfile.mkdtemp(prefix="opmiere_096_"))
    try:
        client = TestClient(app)
        bundle = root / "l.opm"
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
        assert client.post(
            "/api/place_batch",
            json={"paths": [str(v)], "sequential": True},
        ).status_code == 200

        tl = client.get("/api/project/timeline").json()
        clip_id = tl["tracks"][0]["clips"][0]["id"]

        lay = client.post(
            "/api/clip/layout",
            json={
                "clip_id": clip_id,
                "start_frame": 5,
                "refresh_preview": False,
                "quick_preview": True,
            },
        )
        assert lay.status_code == 200, lay.text
        assert "timeline" in lay.json()

        meta = client.post(
            "/api/clip/meta",
            json={"clip_id": clip_id, "name": "Hero"},
        )
        assert meta.status_code == 200, meta.text
        assert meta.json().get("timeline")

        client.post(
            "/api/clip/fades",
            json={
                "clip_id": clip_id,
                "fade_in_frames": 3,
                "fade_out_frames": 6,
            },
        )
        fades = client.get(f"/api/clip/fades/{clip_id}")
        assert fades.status_code == 200, fades.text
        body = fades.json()
        assert body.get("fade_in_frames") == 3
        assert body.get("fade_out_frames") == 6

        fx = client.post(
            "/api/clips/effect",
            json={
                "clip_ids": [clip_id],
                "effect": {
                    "type": "text",
                    "content": "Hello",
                    "position": "bottom",
                    "size": 36,
                },
            },
        )
        assert fx.status_code == 200, fx.text

        plan = client.get("/api/preview/openshot_plan?height=180")
        assert plan.status_code == 200, plan.text
        # plan may be empty-ish without OpenShot but endpoint should answer
        assert isinstance(plan.json(), dict)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_layout_os_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/layout" in ts
    assert "/api/clip/meta" in ts
    assert "/api/clip/fades/" in ts
    assert "showOpenshotPlan" in ts
    assert "grabOpenshotFrame" in ts
    assert "enrichSelectionFades" in ts
    assert 'data-fx="text"' in (
        root / "ui-desktop" / "index.html"
    ).read_text(encoding="utf-8") or 'data-fx="text"' in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-os-plan"' in html
    assert 'id="btn-os-frame"' in html
    assert 'data-fx="text"' in html
    assert 'data-fx="sharpen"' in html
