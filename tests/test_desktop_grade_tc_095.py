"""Desktop grade FX, TC API, preview refresh, project state (0.4.55)."""

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
            "-f", "lavfi", "-i", "color=c=teal:s=160x90:d=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_tc_grade_refresh_state():
    root = Path(tempfile.mkdtemp(prefix="opmiere_095_"))
    try:
        client = TestClient(app)
        bundle = root / "g.opm"
        assert client.post(
            "/api/project/create",
            json={
                "bundle_path": str(bundle),
                "fps": 30,
                "width": 160,
                "height": 90,
            },
        ).status_code == 200

        tc = client.post("/api/tc/format", json={"frame": 90})
        assert tc.status_code == 200, tc.text
        assert tc.json().get("tc")

        parsed = client.post("/api/tc/parse", json={"tc": "00:00:01:15"})
        assert parsed.status_code == 200, parsed.text
        assert parsed.json().get("frame") == 45

        v = root / "v.mp4"
        _vid(v)
        assert client.post(
            "/api/place_batch",
            json={"paths": [str(v)], "sequential": True},
        ).status_code == 200

        st = client.get("/api/project/state")
        assert st.status_code == 200, st.text
        assert "tracks" in st.json() or "media" in st.json()

        tl = client.get("/api/project/timeline").json()
        clip_id = tl["tracks"][0]["clips"][0]["id"]
        fx = client.post(
            "/api/clips/effect",
            json={
                "clip_ids": [clip_id],
                "effect": {
                    "type": "color",
                    "brightness": 0.05,
                    "contrast": 1.05,
                    "saturation": 1.0,
                },
            },
        )
        assert fx.status_code == 200, fx.text
        assert "timeline" in fx.json()

        # build once then quick refresh
        client.post("/api/preview/ensure", json={"height": 180, "fps": 8})
        ref = client.post(
            "/api/preview/refresh", json={"quick": True, "force": False}
        )
        assert ref.status_code == 200, ref.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_grade_tc_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "applyFxPreset" in ts
    assert "refreshPreviewProxy" in ts
    assert "showProjectState" in ts
    assert "/api/tc/parse" in ts
    assert "/api/tc/format" in ts
    assert "/api/clips/effect" in ts
    assert "/api/preview/refresh" in ts
    assert "/api/project/state" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-proxy-refresh"' in html
    assert 'id="btn-project-state"' in html
    assert 'data-fx="bright"' in html
    assert 'data-fx="vintage"' in html
