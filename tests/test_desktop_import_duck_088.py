"""Desktop import EDL/cutlist + ASR + duck + media status (0.4.48)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={sec}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_edl_roundtrip_import():
    root = Path(tempfile.mkdtemp(prefix="opmiere_088_"))
    try:
        client = TestClient(app)
        bundle = root / "p.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        a = root / "clip.mp4"
        _vid(a)
        assert client.post(
            "/api/place_batch", json={"paths": [str(a)], "sequential": True}
        ).status_code == 200
        edl_path = root / "seq.edl"
        assert client.post(
            "/api/export/edl", json={"path": str(edl_path), "title": "rt"}
        ).status_code == 200
        # clear by re-open empty-ish: create new project
        bundle2 = root / "p2.opm"
        assert client.post(
            "/api/project/create",
            json={"bundle_path": str(bundle2), "fps": 30, "width": 160, "height": 90},
        ).status_code == 200
        # media must be in bin — re-import file
        assert client.post(
            "/api/place_batch", json={"paths": [str(a)], "sequential": True}
        ).status_code == 200
        # wipe timeline clips via extract/delete is hard; import_edl with replace
        r = client.post(
            "/api/import/edl",
            json={"path": str(edl_path), "replace_track": True},
        )
        assert r.status_code == 200, r.text
        assert "timeline" in r.json()

        st = client.get("/api/media/status")
        assert st.status_code == 200

        # duck needs 2 audio tracks — create if possible
        client.post("/api/track?kind=audio")
        client.post("/api/track?kind=audio")
        tl = client.get("/api/project/timeline").json()
        aids = [t["id"] for t in tl["tracks"] if t["kind"] == "audio"]
        if len(aids) >= 2:
            d = client.post(
                "/api/duck",
                json={"track_id": aids[0], "against_track_id": aids[1]},
            )
            assert d.status_code == 200, d.text
            c = client.post("/api/duck/clear", json={"track_id": aids[0]})
            assert c.status_code == 200, c.text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_import_duck_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "importEdlFile" in ts
    assert "importCutlistFile" in ts
    assert "transcribeSelection" in ts
    assert "duckSelection" in ts
    assert "/api/import/edl" in ts
    assert "/api/media/transcribe" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-import-edl"' in html
    assert 'id="btn-transcribe"' in html
    assert 'id="btn-duck"' in html
    assert 'id="btn-media-status"' in html
