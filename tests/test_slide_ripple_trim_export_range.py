"""slide_clip, ripple_trim, export_range."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, dur: float = 1.0, color: str = "blue") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_slide_clip(tmp_path: Path):
    paths = [tmp_path / f"{c}.mp4" for c in ("a", "b", "c")]
    for p, col in zip(paths, ("red", "green", "blue")):
        _vid(p, 1.0, col)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    clips = []
    start = 0
    for p in paths:
        m = ed.import_media(p, "video")
        # each 20 frames on timeline from full head of media
        c = ed.add_clip(tr.id, m.id, start, 0, 20)
        clips.append(c)
        start = c.end
    a, b, c = clips
    total = c.end
    ed.slide_clip(b.id, 4)
    a = ed._find_clip(a.id)
    b = ed._find_clip(b.id)
    c = ed._find_clip(c.id)
    assert a.src_out == 24
    assert b.start == 24
    assert b.timeline_duration_frames == 20
    assert c.src_in == 4
    assert c.start == b.end
    assert c.end == total
    ed.export(tmp_path / "slide.mp4")


def test_ripple_trim_shortens_and_pulls(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, 1.0, "red")
    _vid(b, 1.0, "blue")
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ma = ed.import_media(a, "video")
    mb = ed.import_media(b, "video")
    ca = ed.add_clip(tr.id, ma.id, 0, 0, 20)
    cb = ed.add_clip(tr.id, mb.id, 20, 0, 20)
    ed.ripple_trim(ca.id, new_src_out=12)
    ca = ed._find_clip(ca.id)
    cb = ed._find_clip(cb.id)
    assert ca.src_out == 12
    assert cb.start == ca.end == 12


def test_export_range(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, 1.2, "white")
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    out = tmp_path / "seg.mp4"
    r = ed.export_range(out, 0.1, 0.5)
    assert Path(r["path"]).exists()
    assert r["duration_seconds"] == 0.4
    from opmiere.render.probe import probe
    info = probe(r["path"])
    assert 0.3 < info.duration_seconds < 0.55
