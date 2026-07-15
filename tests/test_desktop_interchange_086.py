"""Desktop EDL/cutlist export + rotate/relink (0.4.46)."""

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
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_edl_cutlist_rotate():
    root = Path(tempfile.mkdtemp(prefix="opmiere_086_"))
    try:
        client = TestClient(app)
        bundle = root / "x.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        a = root / "a.mp4"
        _vid(a)
        assert client.post(
            "/api/place_batch", json={"paths": [str(a)], "sequential": True}
        ).status_code == 200
        edl_path = root / "out.edl"
        r = client.post("/api/export/edl", json={"path": str(edl_path), "title": "t"})
        assert r.status_code == 200, r.text
        assert edl_path.is_file()
        assert "TITLE:" in edl_path.read_text(encoding="utf-8")

        csv_path = root / "out.csv"
        r2 = client.post(
            "/api/export/cutlist", json={"path": str(csv_path), "format": "csv"}
        )
        assert r2.status_code == 200, r2.text
        assert csv_path.is_file()

        cid = client.get("/api/project/timeline").json()["tracks"][0]["clips"][0]["id"]
        r3 = client.post("/api/clip/rotate", json={"clip_id": cid, "degrees": 90})
        assert r3.status_code == 200, r3.text
        r4 = client.post(
            "/api/clip/reset_transform",
            json={"clip_id": cid, "position": True, "crop": True, "rotate": True},
        )
        assert r4.status_code == 200, r4.text

        d = client.get("/api/desktop/export_dir")
        assert d.status_code == 200
        assert d.json().get("path")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_interchange_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "exportEdl" in ts
    assert "exportCutlist" in ts
    assert "rotateSelection" in ts
    assert "relinkSelectionToBin" in ts
    assert "/api/export/edl" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-export-edl"' in html
    assert 'id="btn-export-cutlist"' in html
    assert 'id="btn-rot-p90"' in html
    assert 'id="btn-relink"' in html
