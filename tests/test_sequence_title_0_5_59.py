"""sequence_from_media + create_title_card + path-C reverse/freeze tags."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION, build_openshot_plan


def _vid(path: Path, d: float = 0.6, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_sequence_from_media():
    root = Path(tempfile.mkdtemp(prefix="opmiere_seq_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.5, "navy")
        _vid(b, 0.5, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ma = ed.import_media(a, "video")
        mb = ed.import_media(b, "video")
        r = ed.sequence_from_media(
            [ma.id, mb.id], tr.id, start_frame=0, transition="cross_dissolve",
            transition_frames=6,
        )
        assert r["count"] == 2
        clips = tr.clips_in_order()
        assert len(clips) == 2
        assert clips[1].transition_in is not None
        assert clips[0].end > clips[0].start
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_create_title_card():
    root = Path(tempfile.mkdtemp(prefix="opmiere_title_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        r = ed.create_title_card("Hello", tr.id, 0, duration_frames=60)
        assert r["clip_id"]
        clip = ed._find_clip(r["clip_id"])
        assert clip.timeline_duration_frames == 60
        types = [e.get("type") for e in clip.effects]
        assert "text" in types
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert plan["clips"][0].get("text", {}).get("content") == "Hello"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_path_c_freeze_tag():
    root = Path(tempfile.mkdtemp(prefix="opmiere_frz_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        fr = ed.freeze_frame(c.id, duration_frames=15)
        plan = build_openshot_plan(ed.project, ed.bundle, height=180)
        assert int(plan.get("adapter_version") or 0) >= 18
        assert int(ADAPTER_VERSION) >= 18
        still = next(x for x in plan["clips"] if x["id"] == fr["clip_id"])
        assert still.get("freeze_still") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_59():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/sequence/from_media" in app
    assert "/api/title_card" in app
    assert "def sequence_from_media" in mcp
    assert "def create_title_card" in mcp
    assert 'id="btn-seq-media"' in html
    assert 'id="btn-title-card"' in html
    assert "sequenceFromMediaUi" in ts
    assert "titleCardUi" in ts
