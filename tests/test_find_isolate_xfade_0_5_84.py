"""find_clips + isolate_clips + apply_crossfades + markers_from_hard_cuts (0.5.84)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_find_and_isolate():
    root = Path(tempfile.mkdtemp(prefix="opmiere_find_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.4, "navy")
        _vid(b, 0.4, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, c1.end)
        c1.name = "Hero A"
        c2.name = "B-roll"
        ed.set_clip_watermark(c1.id, "x")
        found = ed.find_clips(name_contains="hero")
        assert found["count"] == 1
        assert found["clips"][0]["clip_id"] == c1.id
        fx = ed.find_clips(has_effect="watermark")
        assert fx["count"] == 1
        iso = ed.isolate_clips([c1.id])
        assert c1.muted is False
        assert c2.muted is True
        assert iso["muted_count"] >= 1
        ed.unmute_all_clips()
        assert c2.muted is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_crossfades_and_markers_from_hard_cuts():
    root = Path(tempfile.mkdtemp(prefix="opmiere_xfade_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        c = root / "c.mp4"
        _vid(a, 0.5)
        _vid(b, 0.5)
        _vid(c, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        x = ed.place_from_file(a, "video", tr.id, 0)
        y = ed.place_from_file(b, "video", tr.id, x.end)
        ed.place_from_file(c, "video", tr.id, y.end)
        # ensure hard cuts (no transitions)
        for cl in tr.clips:
            cl.transition_in = None
        r = ed.apply_crossfades_on_track(tr.id, duration_frames=6)
        assert r.get("count", 0) >= 1 or len(r.get("applied") or []) >= 1 or any(
            cl.transition_in for cl in tr.clips
        )
        # rebuild hard cuts for marker test: clear transitions and re-sequence
        with ed._mutate():
            cursor = 0
            for cl in tr.clips_in_order():
                cl.transition_in = None
                cl.start = cursor
                cursor = cl.end
        m = ed.markers_from_hard_cuts(tr.id, prefix="Cut ")
        assert m["count"] >= 1
        assert m["hard_cut_count"] >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_84():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clips/find" in app
    assert "/api/clips/isolate" in app
    assert "/api/track/crossfades" in app
    assert "def find_clips" in mcp
    assert "def isolate_clips" in mcp
    assert 'id="btn-isolate"' in html
    assert "isolateSelectionUi" in ts
