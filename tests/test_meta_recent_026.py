"""0.2.6: clip meta, recent projects, autosave dirty flag."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.recent import CLIP_COLORS, clear_recent, list_recent, touch_recent

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_clip_meta_roundtrip(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c = ed.place_from_file(v, "video", tr.id, 0)
    r = ed.set_clip_meta(c.id, name="Hook", color="#9b2226")
    assert r["name"] == "Hook"
    assert r["color"] == "#9b2226"
    ed.save()
    ed2 = Editor.open(tmp_path / "p.opm")
    c2 = ed2.project.tracks[0].clips[0]
    assert c2.name == "Hook"
    assert c2.color == "#9b2226"
    tv = ed2.timeline_view()
    assert tv["tracks"][0]["clips"][0]["label"] == "Hook"


def test_recent_and_dirty(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("OPMIERE_CONFIG_DIR", str(cfg))
    clear_recent()
    v = tmp_path / "v.mp4"
    _vid(v)
    ed = Editor.create(tmp_path / "rec.opm", fps=FPS, width=160, height=90)
    recent = list_recent()
    assert any(Path(p["path"]).name == "rec.opm" for p in recent["projects"])
    assert ed.is_dirty() is False
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    assert ed.is_dirty() is True
    ed.save()
    assert ed.is_dirty() is False
    ed.set_autosave(True)
    ed.move_clip(ed.project.tracks[0].clips[0].id, 0)
    # autosave clears dirty
    assert ed.is_dirty() is False


def test_web_meta_recent(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient
    from opmiere.web.app import app

    monkeypatch.setenv("OPMIERE_CONFIG_DIR", str(tmp_path / "cfg2"))
    clear_recent()
    v = tmp_path / "v.mp4"
    _vid(v)
    client = TestClient(app)
    bundle = tmp_path / "w.opm"
    assert client.post("/api/project/create", json={
        "bundle_path": str(bundle), "fps": FPS, "width": 160, "height": 90,
    }).status_code == 200
    p = client.post("/api/place", json={"path": str(v), "kind": "video"})
    cid = p.json()["id"]
    r = client.post("/api/clip/meta", json={
        "clip_id": cid, "name": "A", "color": "#0a9396",
    })
    assert r.status_code == 200
    assert r.json()["name"] == "A"
    r = client.get("/api/recent")
    assert r.status_code == 200
    assert r.json()["count"] >= 1
    r = client.get("/api/clip/colors")
    assert len(r.json()["colors"]) == len(CLIP_COLORS)
    r = client.post("/api/autosave", json={"enabled": True})
    assert r.json()["autosave"] is True
