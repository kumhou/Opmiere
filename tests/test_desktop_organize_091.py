"""Desktop organize: mix, gaps, select, rename, track move (0.4.51)."""

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
            "-f", "lavfi", "-i", "color=c=maroon:s=160x90:d=0.4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_organize_apis():
    root = Path(tempfile.mkdtemp(prefix="opmiere_091_"))
    try:
        client = TestClient(app)
        bundle = root / "o.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        assert client.post(
            "/api/place_batch",
            json={"paths": [str(a), str(b)], "sequential": True},
        ).status_code == 200

        mix = client.get("/api/mix")
        assert mix.status_code == 200
        assert "audio_tracks" in mix.json() or "audio_track_count" in mix.json()

        gaps = client.post("/api/gaps/find", json={"from_frame": 0, "min_gap_frames": 1})
        assert gaps.status_code == 200

        tl = client.get("/api/project/timeline").json()
        clips = tl["tracks"][0]["clips"]
        assert len(clips) >= 2
        # set color on first
        cid = clips[0]["id"]
        client.post(
            "/api/clips/meta",
            json={"clip_ids": [cid], "color": "#ff0000"},
        )
        byc = client.post("/api/clips/by_color", json={"color": "#ff0000"})
        assert byc.status_code == 200

        ir = client.post(
            "/api/clips/in_range",
            json={"start_frame": 0, "end_frame": 99999, "partial": True},
        )
        assert ir.status_code == 200

        ren = client.post(
            "/api/clips/rename",
            json={"pattern": "Shot{nn}", "clip_ids": [cid]},
        )
        assert ren.status_code == 200, ren.text

        tid = tl["tracks"][0]["id"]
        client.post("/api/track?kind=video")
        mv = client.post("/api/track/move", json={"track_id": tid, "delta": 1})
        assert mv.status_code == 200, mv.text

        client.post(
            "/api/markers",
            json={"frame": 10, "label": "A"},
        )
        sh = client.post("/api/markers/shift", json={"delta_frames": 5})
        assert sh.status_code == 200

        mb = client.post(
            "/api/clips/move_block",
            json={"clip_ids": [cid], "to_frame": 3, "follow_links": False},
        )
        assert mb.status_code == 200, mb.text

        ca = client.post("/api/gaps/close_all", json={"from_frame": 0})
        assert ca.status_code == 200, ca.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_organize_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "refreshMixConsole" in ts
    assert "findGapsUi" in ts
    assert "selectClipsInIO" in ts
    assert "moveBlockToPlayhead" in ts
    assert "/api/mix" in ts
    assert "/api/gaps/find" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-mix"' in html
    assert 'id="btn-sel-io"' in html
    assert 'id="btn-block-ph"' in html
    assert 'id="mix-out"' in html
