"""ripple_delete, close_gaps, detach_audio (J/L craft)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _av(path: Path, color: str = "blue", dur: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_ripple_delete_closes_hole(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    c = tmp_path / "c.mp4"
    _av(a, "red", 0.5)
    _av(b, "green", 0.5)
    _av(c, "blue", 0.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ca = ed.place_from_file(a, "video", tr.id, 0)
    cb = ed.place_from_file(b, "video", tr.id, ca.end)
    cc = ed.place_from_file(c, "video", tr.id, cb.end)
    mid_start_before = cc.start
    r = ed.ripple_delete(cb.id)
    assert r["deleted_id"] == cb.id
    assert r["frames_closed"] > 0
    assert ca.id in [x.id for x in tr.clips] or any(x.id == ca.id for x in tr.clips)
    ordered = tr.clips_in_order()
    assert len(ordered) == 2
    assert ordered[0].id == ca.id
    assert ordered[1].id == cc.id
    assert ordered[1].start < mid_start_before
    assert ordered[1].start == ordered[0].end
    out = tmp_path / "out.mp4"
    ed.export(out)
    assert out.exists()


def test_close_gaps(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _av(a, "red", 0.4)
    _av(b, "blue", 0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ca = ed.place_from_file(a, "video", tr.id, 0)
    # leave a hole: place b later
    mb = ed.import_media(b, "video")
    ed.add_clip(tr.id, mb.id, ca.end + 30, 0, mb.duration_frames)
    r = ed.close_gaps(tr.id)
    ordered = tr.clips_in_order()
    assert ordered[1].start == ordered[0].end
    assert r["moved"]


def test_detach_audio_jcut_exports(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _av(v, "green", 0.8)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    clip = ed.place_from_file(v, "video", tr.id, 0)
    # J-cut: audio starts 6 frames earlier (clamped to 0)
    det = ed.detach_audio(clip.id, audio_start_offset_frames=-6)
    assert det["audio_clip_id"]
    assert det["audio_start"] == 0
    audio_tracks = [t for t in ed.project.tracks if t.kind == "audio"]
    assert len(audio_tracks) >= 1
    assert any(t.clips for t in audio_tracks)
    out = tmp_path / "jcut.mp4"
    ed.export(out)
    assert out.exists() and out.stat().st_size > 500
