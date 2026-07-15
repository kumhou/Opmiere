"""Desktop transitions, empty tracks, append, plan_edit (0.4.52)."""

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
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_transitions_and_tracks():
    root = Path(tempfile.mkdtemp(prefix="opmiere_092_"))
    try:
        client = TestClient(app)
        bundle = root / "x.opm"
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
        tl = client.get("/api/project/timeline").json()
        tid = tl["tracks"][0]["id"]
        r = client.post(
            "/api/transitions/apply_on_cuts",
            json={
                "track_id": tid,
                "transition_type": "cross_dissolve",
                "duration_frames": 6,
            },
        )
        assert r.status_code == 200, r.text
        r2 = client.post(
            "/api/transitions/clear", json={"track_id": tid}
        )
        assert r2.status_code == 200, r2.text

        # empty track then remove
        client.post("/api/track?kind=audio")
        r3 = client.post(
            "/api/tracks/remove_empty", json={"keep_one_per_kind": True}
        )
        assert r3.status_code == 200, r3.text

        r4 = client.post(
            "/api/track/name", json={"track_id": tid, "name": "A-roll"}
        )
        assert r4.status_code == 200, r4.text

        media = client.get("/api/media").json()["media"]
        mid = media[0]["id"]
        r5 = client.post(
            "/api/append_media",
            json={"media_id": mid, "track_id": tid},
        )
        assert r5.status_code == 200, r5.text

        r6 = client.post("/api/look", json={"look": "documentary"})
        assert r6.status_code == 200, r6.text

        paths = [m.get("abs_path") or str(root / "a.mp4") for m in media[:2]]
        r7 = client.post(
            "/api/plan_edit",
            json={
                "paths": [str(a), str(b)],
                "apply": False,
                "b_roll_mode": "overlay",
            },
        )
        assert r7.status_code == 200, r7.text
        assert "plan" in r7.json()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_xfade_append_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "xfadeAllOnTrack" in ts
    assert "appendBinMedia" in ts
    assert "planEditFromBin" in ts
    assert "/api/transitions/apply_on_cuts" in ts
    assert "/api/append_media" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-xfade-all"' in html
    assert 'id="btn-append-bin"' in html
    assert 'id="btn-plan-edit"' in html
    assert 'id="btn-rm-empty"' in html
