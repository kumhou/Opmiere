"""Desktop magnetic time: ripple nudge + insert/extract time (0.4.42)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, sec: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=orange:s=160x90:d={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_ripple_nudge_and_insert_time():
    root = Path(tempfile.mkdtemp(prefix="opmiere_082_"))
    try:
        client = TestClient(app)
        bundle = root / "m.opm"
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
        clips = tl["tracks"][0]["clips"]
        assert len(clips) >= 2
        first = clips[0]
        second = clips[1]
        assert second["start_frame"] > first["start_frame"]

        r = client.post(
            "/api/ripple_nudge",
            json={"clip_id": first["id"], "delta_frames": 10, "include_self": True},
        )
        assert r.status_code == 200, r.text
        tl2 = r.json()["timeline"]
        c1 = next(c for c in tl2["tracks"][0]["clips"] if c["id"] == first["id"])
        c2 = next(c for c in tl2["tracks"][0]["clips"] if c["id"] == second["id"])
        assert c1["start_frame"] == first["start_frame"] + 10
        assert c2["start_frame"] == second["start_frame"] + 10

        # insert time at 0 pushes both further
        tid = tl2["tracks"][0]["id"]
        r2 = client.post(
            "/api/insert_time",
            json={"track_id": tid, "at_frame": 0, "frames": 5},
        )
        assert r2.status_code == 200, r2.text
        tl3 = r2.json()["timeline"]
        c1b = next(c for c in tl3["tracks"][0]["clips"] if c["id"] == first["id"])
        assert c1b["start_frame"] == c1["start_frame"] + 5

        # extract_time removes a hole
        start = c1b["start_frame"]
        end = start + 3
        r3 = client.post(
            "/api/extract_time",
            json={"track_id": tid, "start_frame": start, "end_frame": end, "ripple": True},
        )
        assert r3.status_code == 200, r3.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_magnetic_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "rippleNudgeSelection" in ts
    assert "insertTimeAtPlayhead" in ts
    assert "extractTimeIO" in ts
    assert "/api/ripple_nudge" in ts
    assert "/api/insert_time" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-insert-15"' in html
    assert 'id="btn-ripple-m"' in html
    assert 'id="btn-extract-time"' in html
