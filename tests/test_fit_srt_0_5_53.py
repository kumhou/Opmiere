"""fit_clips_to_markers + markers_from_srt + path-C text."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan, clip_visual_props


def _vid(path: Path, d: float = 2.0, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_fit_clips_to_markers_speed():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fitm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)  # ~60f at 30fps
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=0, label="A")
        ed.add_marker(frame=30, label="B")
        # full media is ~60f; fit into 0..30 slot → speed ~2
        r = ed.fit_clips_to_markers([c.id], method="speed", max_start_delta=2)
        assert r["count"] == 1
        clip = ed._find_clip(c.id)
        assert abs(clip.speed - 2.0) < 0.15 or clip.speed >= 1.5
        assert clip.start == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_markers_from_srt():
    root = Path(tempfile.mkdtemp(prefix="opmiere_srt_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        srt = (
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "Hello world\n"
            "\n"
            "2\n"
            "00:00:01,500 --> 00:00:02,000\n"
            "Second line\n"
        )
        r = ed.markers_from_srt(text=srt, label_from_text=True)
        assert r["count"] == 2
        assert r["cue_count"] == 2
        labels = [m.label for m in ed.project.markers]
        assert "Hello world" in labels
        assert "Second line" in labels
        frames = sorted(m.frame for m in ed.project.markers)
        assert frames[0] == 0
        assert frames[1] == 45  # 1.5s * 30
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_text_mapped():
    root = Path(tempfile.mkdtemp(prefix="opmiere_txt_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.8)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(
            c.id,
            {
                "type": "text",
                "content": "Title",
                "position": "bottom",
                "size": 40,
                "border_width": 2,
            },
        )
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "text" in vis["mapped_effects"]
        assert vis["text"]["content"] == "Title"
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 14
        assert int(ADAPTER_VERSION) >= 14
        assert plan["clips"][0].get("text", {}).get("content") == "Title"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_53():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clips/fit_to_markers" in app
    assert "/api/markers/from_srt" in app
    assert "def fit_clips_to_markers" in mcp
    assert "def markers_from_srt" in mcp
    assert 'id="btn-fit-mkr"' in html
    assert 'id="btn-srt-mkr"' in html
    assert "fitToMarkersUi" in ts
    assert "importSrtMarkersUi" in ts
