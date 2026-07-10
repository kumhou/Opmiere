"""0.1.8: cut templates + style asset resolve."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.cut_templates import get_template, list_templates
from opmiere.render.style_presets import list_style_assets, resolve_style_asset

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _wav(path: Path, dur: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=220:duration={dur}",
            "-c:a", "pcm_s16le", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_list_and_get_templates():
    names = list_templates()["names"]
    assert "talking_head" in names
    assert "short_form" in names
    t = get_template("口播")
    assert t["id"] == "talking_head"
    assert t["style"]


def test_apply_cut_template_dry_and_live(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    m = tmp_path / "bed.wav"
    _vid(a, "red")
    _vid(b, "blue")
    _wav(m)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    dry = ed.apply_cut_template(
        "talking_head", paths=[a, b, m], dry_run=True,
    )
    assert dry["applied"] is False
    assert dry["style"] == "documentary"
    assert len(dry["a_roll"]) == 2
    assert dry["music"]

    live = ed.apply_cut_template(
        "talking_head", paths=[a, b, m], dry_run=False,
    )
    assert live["applied"] is True
    assert live["batch"]["placed_count"] == 2
    assert live.get("music_track_id")
    # style applied without error
    assert live.get("style_result") and "error" not in live["style_result"]
    vclips = [c for t in ed.project.tracks if t.kind == "video" for c in t.clips]
    assert len(vclips) == 2


def test_short_form_template(tmp_path: Path):
    a = tmp_path / "h.mp4"
    _vid(a, "white", 0.4)
    ed = Editor.create(tmp_path / "s.opm", fps=FPS, width=160, height=90)
    r = ed.apply_cut_template("short_form", a_roll=[a])
    assert r["applied"]
    assert r["style"] == "thriller"


def test_style_assets_api_and_resolve(tmp_path: Path, monkeypatch):
    root = tmp_path / "assets"
    (root / "luts").mkdir(parents=True)
    cube = root / "luts" / "cold_terror.cube"
    # minimal fake cube header — file existence only for resolve
    cube.write_text("TITLE \"test\"\n", encoding="utf-8")
    monkeypatch.setenv("OPMIERE_STYLE_ASSETS", str(root))
    found = resolve_style_asset("cold_terror.cube", kind="lut")
    assert found is not None
    assert found.name == "cold_terror.cube"
    inv = list_style_assets()
    assert any("cold_terror" in x for x in inv["luts"])


def test_web_templates(tmp_path: Path):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    v = tmp_path / "v.mp4"
    _vid(v)
    client = TestClient(app)
    r = client.get("/api/templates")
    assert r.status_code == 200
    assert "talking_head" in r.json()["names"]

    bundle = tmp_path / "w.opm"
    assert client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    r = client.post("/api/templates/apply", json={
        "template": "vlog",
        "paths": [str(v)],
        "dry_run": True,
    })
    assert r.status_code == 200
    assert r.json()["applied"] is False
    r = client.post("/api/templates/apply", json={
        "template": "vlog",
        "paths": [str(v)],
        "dry_run": False,
    })
    assert r.status_code == 200
    assert r.json()["applied"] is True
