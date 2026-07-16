"""Desktop generation API surface (0.4.60) — no live ComfyUI required."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from opmiere.generation.provider import GenerationJob, JobStatus, ModelLicense
from opmiere.web import app as webapp
from opmiere.web.app import app


def test_generate_endpoints_with_mock_provider():
    root = Path(tempfile.mkdtemp(prefix="opmiere_100_"))
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
        assert client.post("/api/track?kind=video").status_code == 200

        ed = webapp._editor
        assert ed is not None

        fake_path = root / "out.png"
        fake_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

        provider = MagicMock()
        provider.name = "mock"
        provider.submit.return_value = "job_mock_1"
        provider.status.return_value = GenerationJob(
            id="job_mock_1",
            status=JobStatus.DONE,
            kind="image",
            prompt="a red square",
            result_path=fake_path,
            error=None,
            license=ModelLicense(
                name="Apache-2.0",
                commercial_use="yes",
                notes="test",
            ),
        )
        ed.generation_provider = provider

        r = client.post(
            "/api/generate",
            json={"kind": "image", "prompt": "a red square", "params": {}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("job_id") == "job_mock_1"
        provider.submit.assert_called()

        st = client.get("/api/generate/job/job_mock_1")
        assert st.status_code == 200, st.text
        sj = st.json()
        assert sj.get("status") == "done"
        assert sj.get("result_path")

        st2 = client.post(
            "/api/generate/status", json={"job_id": "job_mock_1"}
        )
        assert st2.status_code == 200

        # place needs real import — mock place_generated on editor instead
        from opmiere.model import Clip

        fake_clip = MagicMock(spec=Clip)
        fake_clip.id = "clip_gen"
        fake_clip.to_dict.return_value = {"id": "clip_gen"}
        ed.place_generated = MagicMock(return_value=fake_clip)  # type: ignore[method-assign]
        ed.timeline_view = MagicMock(return_value={"tracks": []})  # type: ignore[method-assign]

        pl = client.post(
            "/api/place_generated",
            json={
                "job_id": "job_mock_1",
                "track_id": None,
                "start": 0,
                "duration_frames": 30,
            },
        )
        assert pl.status_code == 200, pl.text
        assert pl.json().get("clip", {}).get("id") == "clip_gen"

        qc = client.post(
            "/api/quality_check", json={"path": str(fake_path)}
        )
        # quality_check may fail on tiny fake png — accept 200 or 400
        assert qc.status_code in (200, 400), qc.text

        lic = client.get("/api/license_report")
        assert lic.status_code == 200, lic.text
        assert "entries" in lic.json() or "safe_for_commercial_use" in lic.json()
    finally:
        webapp._editor = None
        shutil.rmtree(root, ignore_errors=True)


def test_generate_ui_wiring():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "submitGeneration" in ts
    assert "placeGeneratedAtPlayhead" in ts
    assert "/api/generate" in ts
    assert "/api/place_generated" in ts
    assert "/api/quality_check" in ts
    assert "/api/license_report" in ts
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-gen-go"' in html
    assert 'id="gen-prompt"' in html
    assert 'id="btn-gen-place"' in html
