"""Desktop detach audio / auto-link / fit-fill / swap (0.4.44)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, sec: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=purple:s=160x90:d={sec}",
            "-f", "lavfi", "-i", f"sine=f=440:d={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_detach_swap_fit_apis():
    root = Path(tempfile.mkdtemp(prefix="opmiere_084_"))
    try:
        client = TestClient(app)
        bundle = root / "c.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        assert client.post(
            "/api/place_batch", json={"paths": [str(a), str(b)], "sequential": True}
        ).status_code == 200
        tl = client.get("/api/project/timeline").json()
        vclips = tl["tracks"][0]["clips"]
        assert len(vclips) >= 2
        cid = vclips[0]["id"]

        r = client.post(
            "/api/clip/detach_audio",
            json={"clip_id": cid, "link": True},
        )
        assert r.status_code == 200, r.text
        tl2 = r.json()["timeline"]
        atracks = [t for t in tl2["tracks"] if t["kind"] == "audio"]
        assert atracks and any(t["clips"] for t in atracks)

        r2 = client.post("/api/auto_link_av", json={"tolerance_frames": 2})
        assert r2.status_code == 200, r2.text

        # fit first clip toward second
        r3 = client.post(
            "/api/clip/fit_to_fill",
            json={"clip_id": cid, "end_frame": None, "clamp": True},
        )
        assert r3.status_code == 200, r3.text

        cids = [c["id"] for c in r3.json()["timeline"]["tracks"][0]["clips"]]
        if len(cids) >= 2:
            r4 = client.post(
                "/api/clips/swap",
                json={"clip_a": cids[0], "clip_b": cids[1]},
            )
            assert r4.status_code == 200, r4.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_craft_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "detachAudioSelection" in ts
    assert "autoLinkAV" in ts
    assert "fitToFillSelection" in ts
    assert "swapSelection" in ts
    assert "/api/clip/detach_audio" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-detach-a"' in html
    assert 'id="btn-auto-link"' in html
    assert 'id="btn-fit-fill"' in html
    assert 'id="btn-swap"' in html
