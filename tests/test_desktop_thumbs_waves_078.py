"""Desktop media thumbs + timeline waveforms (0.4.38)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, seconds: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=green:s=160x90:d={seconds}",
            "-f", "lavfi", "-i", f"sine=f=440:d={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_thumb_and_waveform_apis():
    root = Path(tempfile.mkdtemp(prefix="opmiere_078_"))
    try:
        client = TestClient(app)
        bundle = root / "w.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        vid = root / "a.mp4"
        _vid(vid)
        r = client.post(
            "/api/place_batch",
            json={"paths": [str(vid)], "sequential": True},
        )
        assert r.status_code == 200, r.text
        media = client.get("/api/media").json()["media"]
        assert media
        mid = media[0]["id"]

        thumb = client.get(f"/api/media/{mid}/thumb.jpg?t=0.1&width=64")
        assert thumb.status_code == 200, thumb.text[:200]
        assert thumb.headers.get("content-type", "").startswith("image/")
        assert len(thumb.content) > 50

        wave = client.post("/api/waveform", json={"media_id": mid, "num_peaks": 40})
        assert wave.status_code == 200, wave.text
        peaks = wave.json().get("peaks") or []
        assert len(peaks) >= 8

        # timeline exposes media_id + has_audio for shell
        tl = client.get("/api/project/timeline").json()
        clip = tl["tracks"][0]["clips"][0]
        assert clip.get("media_id") == mid
        assert clip.get("has_audio_media") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_shell_thumb_wave_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "media-thumb" in ts
    assert "thumb.jpg" in ts
    assert "clip-wave" in ts
    assert "/api/waveform" in ts
    assert "loadMissingWaveforms" in ts
    css = (root / "ui-desktop" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "clip-wave" in css
    assert "media-thumb" in css
