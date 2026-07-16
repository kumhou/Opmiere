"""list_marker_slots + clear_markers + path-C subtitles."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=2.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_list_marker_slots_and_clear():
    root = Path(tempfile.mkdtemp(prefix="opmiere_slots_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=0, label="Beat 1")
        ed.add_marker(frame=30, label="Beat 2")
        ed.add_marker(frame=45, label="Scene 1")
        slots = ed.list_marker_slots(include_tail=True)
        assert slots["count"] >= 2
        assert slots["slots"][0]["start_frame"] == 0
        assert slots["slots"][0]["end_frame"] == 30
        r = ed.clear_markers(prefix="Beat")
        assert r["deleted"] == 2
        assert r["remaining"] == 1
        assert ed.project.markers[0].label == "Scene 1"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_subtitles_mapped():
    root = Path(tempfile.mkdtemp(prefix="opmiere_subs_"))
    try:
        v = root / "v.mp4"
        srt = root / "c.srt"
        _vid(v)
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHi\n",
            encoding="utf-8",
        )
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "subtitles", "path": str(srt)})
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "subtitles" in vis["mapped_effects"]
        assert vis["subtitles"]["exists"] is True
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 15
        assert int(ADAPTER_VERSION) >= 15
        assert plan["clips"][0].get("subtitles", {}).get("exists") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_55():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/markers/slots" in app
    assert "/api/markers/clear" in app
    assert "def list_marker_slots" in mcp
    assert "def clear_markers" in mcp
    assert 'id="btn-mkr-slots"' in html
    assert "markerSlotsUi" in ts
