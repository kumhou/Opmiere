"""Desktop keyframes, trim_range, media/proxy, style_assets (0.4.54)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, color: str = "navy", dur: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", f"-i", f"color=c={color}:s=160x90:d={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_style_assets_and_trim_proxy_keyframes():
    root = Path(tempfile.mkdtemp(prefix="opmiere_094_"))
    try:
        client = TestClient(app)
        bundle = root / "k.opm"
        assert client.post(
            "/api/project/create",
            json={
                "bundle_path": str(bundle),
                "fps": 30,
                "width": 160,
                "height": 90,
            },
        ).status_code == 200

        sa = client.get("/api/style_assets")
        assert sa.status_code == 200, sa.text
        body = sa.json()
        assert "luts" in body and "audio" in body and "search_dirs" in body

        a = root / "a.mp4"
        _vid(a, "navy", 1.0)
        assert client.post(
            "/api/place_batch",
            json={"paths": [str(a)], "sequential": True},
        ).status_code == 200

        media = client.get("/api/media").json()["media"]
        mid = media[0]["id"]
        r_proxy = client.post(
            "/api/media/proxy",
            json={"media_id": mid, "height": 180, "force": False},
        )
        assert r_proxy.status_code == 200, r_proxy.text

        # keyframes while timeline is contiguous from 0 (export_preview P0)
        r_kf = client.post("/api/preview/keyframes?count=3&width=160")
        assert r_kf.status_code == 200, r_kf.text
        kf = r_kf.json()
        assert kf.get("count", 0) >= 2
        assert kf.get("frames")

        tl = client.get("/api/project/timeline").json()
        clip = tl["tracks"][0]["clips"][0]
        clip_id = clip["id"]
        start = int(clip.get("start_frame") or clip.get("start") or 0)
        end = start + int(clip.get("duration_frames") or 30)
        # trim source to inner range (still starts at 0 if we use head/tail inside)
        a_f = start + 3
        b_f = max(a_f + 6, end - 3)
        r_trim = client.post(
            "/api/clip/trim_range",
            json={
                "clip_id": clip_id,
                "start_frame": a_f,
                "end_frame": b_f,
                "mode": "normal",
            },
        )
        assert r_trim.status_code == 200, r_trim.text
        assert "timeline" in r_trim.json()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_keyframes_trim_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "reviewKeyframesUi" in ts
    assert "trimSelectionToIO" in ts
    assert "ensureBinMediaProxy" in ts
    assert "showStyleAssets" in ts
    assert "/api/preview/keyframes" in ts
    assert "/api/clip/trim_range" in ts
    assert "/api/media/proxy" in ts
    assert "/api/style_assets" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-keyframes"' in html
    assert 'id="btn-trim-io"' in html
    assert 'id="btn-proxy-one"' in html
    assert 'id="btn-style-assets"' in html
    assert 'id="keyframe-strip"' in html
