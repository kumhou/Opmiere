"""slip_clip and roll_edit."""

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


def test_slip_moves_source_keeps_timeline(tmp_path: Path):
    # 1.0s = 30 frames media; place only middle 15 frames then slip
    v = tmp_path / "v.mp4"
    _vid(v, 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    media = ed.import_media(v, "video")
    # window [5, 20) duration 15
    clip = ed.add_clip(tr.id, media.id, 0, 5, 20)
    start_before = clip.start
    dur_before = clip.timeline_duration_frames
    r = ed.slip_clip(clip.id, 3)
    clip = ed._find_clip(clip.id)
    assert clip.src_in == 8
    assert clip.src_out == 23
    assert clip.start == start_before
    assert clip.timeline_duration_frames == dur_before
    assert r["src_in"]["to"] == 8


def test_slip_clamps_to_media(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _vid(v, 0.5)  # 15 frames
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    media = ed.import_media(v, "video")
    clip = ed.add_clip(tr.id, media.id, 0, 0, 10)
    # slip forward too far — should clamp
    ed.slip_clip(clip.id, 100)
    clip = ed._find_clip(clip.id)
    assert clip.src_out == media.duration_frames
    assert clip.src_out - clip.src_in == 10


def test_roll_edit_moves_cut(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, 1.0, "red")
    _vid(b, 1.0, "blue")
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ma = ed.import_media(a, "video")
    mb = ed.import_media(b, "video")
    # left [0,20) right [20,40) on timeline, full source windows
    left = ed.add_clip(tr.id, ma.id, 0, 0, 20)
    right = ed.add_clip(tr.id, mb.id, 20, 0, 20)
    pair_len = left.timeline_duration_frames + right.timeline_duration_frames
    r = ed.roll_edit(left.id, right.id, 5)
    left = ed._find_clip(left.id)
    right = ed._find_clip(right.id)
    assert left.src_out == 25
    assert right.src_in == 5
    assert right.start == left.end == 25
    assert left.timeline_duration_frames + right.timeline_duration_frames == pair_len
    assert r["edit_frame"] == 25
    ed.export(tmp_path / "roll.mp4")


def test_roll_rejects_non_adjacent(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _vid(a, 0.5)
    _vid(b, 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ma = ed.import_media(a, "video")
    mb = ed.import_media(b, "video")
    left = ed.add_clip(tr.id, ma.id, 0, 0, 10)
    right = ed.add_clip(tr.id, mb.id, 20, 0, 10)  # gap
    try:
        ed.roll_edit(left.id, right.id, 1)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "adjacent" in str(e).lower() or "hard" in str(e).lower()
