"""Desktop native import via place_batch (0.4.33).

Tauri multi-file picker is UI-only; HTTP place_batch remains the source of truth.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from opmiere.web.app import app

FPS = 30


def _vid(path: Path, seconds: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_place_batch_desktop_import_paths():
    root = Path(tempfile.mkdtemp(prefix="opmiere_073_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        client = TestClient(app)
        bundle = root / "shell.opm"
        assert client.post(
            "/api/project/create",
            json={
                "bundle_path": str(bundle),
                "fps": FPS,
                "width": 160,
                "height": 90,
            },
        ).status_code == 200

        r = client.post(
            "/api/place_batch",
            json={"paths": [str(a), str(b)], "sequential": True, "build_proxy": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["result"]["placed_count"] == 2
        assert body["result"]["error_count"] == 0
        assert "timeline" in body
        assert len(body["timeline"]["tracks"]) >= 1

        # missing path reported as error, not 500
        r2 = client.post(
            "/api/place_batch",
            json={"paths": [str(root / "missing.mp4")], "sequential": True},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["result"]["error_count"] == 1

        media = client.get("/api/media").json()
        items = media.get("media") or media.get("items") or media.get("entries") or []
        assert media.get("count", len(items)) >= 2
        assert len(items) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_import_button_in_shell_html():
    html = (Path(__file__).resolve().parents[1] / "ui-desktop" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="btn-import"' in html
    assert 'id="file-import"' in html
    ts = (Path(__file__).resolve().parents[1] / "ui-desktop" / "src" / "main.ts").read_text(
        encoding="utf-8"
    )
    assert "importLocalPaths" in ts
    assert "pickMediaFiles" in ts
    assert "/api/place_batch" in ts
    assert "startImport" in ts
