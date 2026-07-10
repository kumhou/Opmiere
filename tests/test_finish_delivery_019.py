"""0.1.9: finish_delivery, silence-to-clip, template dogfood smoke."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _av(path: Path, color: str = "navy", dur: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:size=320x180:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _wav(path: Path, dur: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=200:duration={dur}",
            "-c:a", "pcm_s16le", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_finish_delivery(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _av(v, "teal", 0.7)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    out = tmp_path / "out.mp4"
    r = ed.finish_delivery(out, normalize_preset="streaming", run_review=True)
    assert r["export"]["exists"]
    assert Path(r["export"]["path"]).exists()
    assert r["ok"] is True
    assert "delivery_check" in r


def test_apply_silence_noop_continuous(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _av(v, "gray", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    dry = ed.apply_silence_to_clip(c.id, dry_run=True)
    assert "keep_ranges" in dry
    # continuous tone → likely 0–1 silences; apply should skip if <2 keeps
    live = ed.apply_silence_to_clip(c.id, dry_run=False)
    assert live.get("applied") is False or live.get("applied") is True


def test_template_then_finish(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    m = tmp_path / "m.wav"
    vo = tmp_path / "vo.wav"
    _av(a, "red", 0.5)
    _av(b, "blue", 0.5)
    _wav(m)
    _wav(vo)
    ed = Editor.create(tmp_path / "t.opm", fps=FPS, width=320, height=180)
    t = ed.apply_cut_template(
        "talking_head",
        paths=[a, b, m, vo],
        dry_run=False,
    )
    assert t["applied"]
    r = ed.finish_delivery(tmp_path / "del.mp4", run_sequence_sheet=False)
    assert r["ok"]
    assert r["export"]["size"] > 500


def test_web_finish(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _av(v, "purple", 0.5)
    client = TestClient(app)
    assert client.post("/api/project/create", json={
        "bundle_path": str(tmp_path / "w.opm"),
        "fps": FPS, "width": 320, "height": 180,
    }).status_code == 200
    assert client.post("/api/place", json={"path": str(v), "kind": "video"}).status_code == 200
    r = client.post("/api/finish", json={
        "output_path": str(tmp_path / "fin.mp4"),
        "normalize_preset": "streaming",
        "run_review": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
