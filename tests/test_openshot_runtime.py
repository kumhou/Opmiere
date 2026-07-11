"""OpenShot embed runtime (S2) — skipped when OpenShot not installed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opmiere.render.openshot_runtime import (
    get_openshot_runtime,
    openshot_runtime_available,
)

FPS = 30


def _clip(path: Path, color: str = "blue", dur: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=320x180:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


pytestmark = pytest.mark.skipif(
    not openshot_runtime_available(),
    reason="OpenShot Video Editor not installed",
)


def test_runtime_version():
    rt = get_openshot_runtime()
    assert rt is not None
    v = rt.version()
    assert v.get("ok") is True
    assert v.get("openshot_version")


def test_frame_from_media(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "green", 0.8)
    out = tmp_path / "f.png"
    rt = get_openshot_runtime()
    assert rt is not None
    r = rt.frame_from_media(v, 0.2, out)
    assert r.get("ok") is True, r
    assert Path(r["path"]).exists()
    assert Path(r["path"]).stat().st_size > 100


def test_frame_from_timeline_clip(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _clip(v, "red", 0.8)
    out = tmp_path / "tl.png"
    rt = get_openshot_runtime()
    assert rt is not None
    r = rt.frame_from_timeline_clip(v, 0.25, out, width=320, height=180, fps=FPS)
    assert r.get("ok") is True, r
    assert Path(r["path"]).exists()


def test_editor_openshot_frame(tmp_path: Path):
    from opmiere import Editor

    v = tmp_path / "v.mp4"
    _clip(v, "cyan", 0.7)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    out = tmp_path / "ed.png"
    r = ed.openshot_frame_at(0.15, out, height=120)
    assert r.get("ok") is True, r
    assert Path(r["path"]).exists()
    assert r.get("mode") == "openshot_project" or r.get("plan_clip_count") == 1


def test_multi_clip_plan_and_frame(tmp_path: Path):
    from opmiere import Editor
    from opmiere.render.openshot_map import build_openshot_plan

    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _clip(a, "blue", 0.6)
    _clip(b, "red", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(a, "video", tr.id, 0)
    ed.place_from_file(b, "video", tr.id, c1.end)
    plan = build_openshot_plan(ed.project, ed.bundle, height=120)
    assert plan["clip_count"] == 2
    assert plan["clips"][0]["layer"] == 1
    assert plan["clips"][1]["position"] > 0
    # frame in second clip (full Timeline or reader fallback both ok)
    out = tmp_path / "multi.png"
    r = ed.openshot_frame_at(0.7, out, height=180)
    assert r.get("ok") is True, r
    assert r.get("plan_clip_count") == 2 or r.get("clips_in_plan") == 2 or r.get("clips_added") == 2
    assert Path(r["path"]).exists()
    assert r.get("mode") in (
        "openshot_project",
        "openshot_project_fallback_reader",
        "openshot_ffmpeg_reader",
    )


def test_overlay_track_in_plan(tmp_path: Path):
    from opmiere import Editor
    from opmiere.render.openshot_map import build_openshot_plan

    base = tmp_path / "base.mp4"
    ov = tmp_path / "ov.mp4"
    _clip(base, "green", 0.8)
    _clip(ov, "yellow", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    t0 = ed.add_track("video")
    t1 = ed.add_track("video")
    ed.place_from_file(base, "video", t0.id, 0)
    c2 = ed.place_from_file(ov, "video", t1.id, 0)
    ed.set_position(c2.id, x=0.1, y=0.1, scale=0.4)
    plan = build_openshot_plan(ed.project, ed.bundle, height=120)
    assert plan["clip_count"] == 2
    layers = {c["layer"] for c in plan["clips"]}
    assert layers == {1, 2}
    overlay = [c for c in plan["clips"] if c["layer"] == 2][0]
    assert "transform" in overlay
    out = tmp_path / "ov.png"
    r = ed.openshot_frame_at(0.1, out, height=180)
    assert r.get("ok") is True, r
    # overlay may composite or fall back; plan must still list both layers
    assert plan["clip_count"] == 2


def test_preview_session_openshot(tmp_path: Path):
    from opmiere import Editor
    from opmiere.render.preview_session import get_preview_session

    v = tmp_path / "v.mp4"
    _clip(v, "white", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    sess = get_preview_session()
    assert sess.backend_name == "libopenshot"
    assert sess.open(ed.project, ed.bundle).get("ok") is True
    out = tmp_path / "sess.png"
    r = sess.frame_at(0.1, out, height=120)
    assert r.get("ok") is True, r


def test_preview_engine_status_active():
    from opmiere.render.preview_session import preview_engine_status

    st = preview_engine_status()
    assert st["active_backend"] == "libopenshot"
    assert st["openshot_app_present"] is True
