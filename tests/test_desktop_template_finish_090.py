"""Desktop templates, finish, replace, copy-track, ASR search (0.4.50)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app


def _vid(path: Path, sec: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=olive:s=160x90:d={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_templates_list_and_replace_copy():
    client = TestClient(app)
    t = client.get("/api/templates")
    assert t.status_code == 200
    names = t.json().get("names") or []
    assert "talking_head" in names

    root = Path(tempfile.mkdtemp(prefix="opmiere_090_"))
    try:
        bundle = root / "t.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b, 0.5)
        assert client.post(
            "/api/place_batch", json={"paths": [str(a)], "sequential": True}
        ).status_code == 200
        media = client.get("/api/media").json()["media"]
        mid_a = media[0]["id"]
        # place second media into bin only via place then we have two media
        assert client.post(
            "/api/place_batch", json={"paths": [str(b)], "sequential": True}
        ).status_code == 200
        media = client.get("/api/media").json()["media"]
        mid_b = [m["id"] for m in media if m["id"] != mid_a][0]
        tl = client.get("/api/project/timeline").json()
        cid = tl["tracks"][0]["clips"][0]["id"]
        r = client.post(
            "/api/clip/replace_edit",
            json={"clip_id": cid, "media_id": mid_b, "mode": "stretch"},
        )
        assert r.status_code == 200, r.text

        tr = client.post("/api/track?kind=video")
        assert tr.status_code == 200
        dest = tr.json()["id"]
        r2 = client.post(
            "/api/clip/copy_to_track",
            json={"clip_id": cid, "track_id": dest, "copy_effects": True},
        )
        assert r2.status_code == 200, r2.text

        # markers import
        r3 = client.post(
            "/api/markers/import",
            json={"text": "0:00 Intro\n0:05 Hook", "format": "youtube"},
        )
        assert r3.status_code == 200, r3.text
        assert len(r3.json().get("markers") or []) >= 1

        # finish needs exportable timeline — may soft-fail delivery but should 200
        out = root / "fin.mp4"
        # silent lavfi sources: skip loudness normalize
        r4 = client.post(
            "/api/finish",
            json={
                "output_path": str(out),
                "normalize_preset": None,
                "delivery_preset": "streaming",
                "run_review": False,
                "run_sequence_sheet": False,
            },
        )
        assert r4.status_code == 200, r4.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_template_finish_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "applyCutTemplate" in ts
    assert "finishDelivery" in ts
    assert "searchTranscriptsUi" in ts
    assert "replaceEditSelection" in ts
    assert "copySelectionToNewTrack" in ts
    assert "/api/templates/apply" in ts
    assert "/api/finish" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-template"' in html
    assert 'id="btn-finish"' in html
    assert 'id="btn-replace-edit"' in html
    assert 'id="btn-copy-track"' in html
