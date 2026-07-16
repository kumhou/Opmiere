"""Agent preflight/finish + pro API surface smoke (0.4.61 foundation)."""

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
            "-f", "lavfi", "-i", "color=c=gray:s=160x90:d=0.4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_agent_preflight_and_pro_routes_exist():
    root = Path(tempfile.mkdtemp(prefix="opmiere_101_"))
    try:
        client = TestClient(app)
        bundle = root / "a.opm"
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
        client.post("/api/place_batch", json={"paths": [str(v)], "sequential": True})

        pf = client.get("/api/agent/preflight")
        assert pf.status_code == 200, pf.text
        body = pf.json()
        assert "next_steps" in body or "ready" in body or "validate" in body

        # interchange / analysis routes respond (may 400 without extras)
        for path, method, payload in [
            ("/api/export/fcpxml", "post", {}),
            ("/api/export/otio", "post", {}),
            ("/api/export/still", "post", {"frame": 0, "width": 160}),
            ("/api/snap_points", "get", None),
            ("/api/preview/invalidate", "post", {}),
            ("/api/analyze/timeline", "post", {}),
        ]:
            if method == "get":
                r = client.get(path)
            else:
                r = client.post(path, json=payload or {})
            assert r.status_code in (200, 400, 500), f"{path} {r.status_code} {r.text[:120]}"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_agent_ui_061():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "runAgentPreflight" in ts
    assert "runAgentFinish" in ts
    assert "/api/agent/preflight" in ts
    assert "/api/agent/finish" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-preflight"' in html
    assert 'id="btn-agent-finish"' in html
