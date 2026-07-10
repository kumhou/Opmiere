"""Room tone fill + segment preview_range."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.room_tone import extract_room_tone, suggest_room_tone

FPS = 30


def _speech_like_with_silence(path: Path) -> None:
    """Tone, silence, tone — room tone can come from the middle gap."""
    # 0.4s tone + 0.8s silence + 0.4s tone
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4,volume=0.3",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo,volume=0",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4,volume=0.3",
            "-filter_complex",
            "[0][1][2]concat=n=3:v=0:a=1,atrim=0:1.6",
            "-t", "1.6", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _video(path: Path, dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=blue:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_suggest_and_extract_room_tone(tmp_path: Path):
    wav = tmp_path / "dlg.wav"
    _speech_like_with_silence(wav)
    sug = suggest_room_tone(wav, min_silence_seconds=0.3, min_donor_seconds=0.2)
    assert sug["ok"] is True
    assert sug["donor"]
    assert sug["donor"]["duration"] >= 0.2
    out = tmp_path / "tone.wav"
    ext = extract_room_tone(
        wav, out,
        start=sug["donor"]["start"],
        end=sug["donor"]["end"],
        loop_to_seconds=2.5,
    )
    assert Path(ext["path"]).exists()
    assert ext["duration_seconds"] >= 0.2
    # looped if donor shorter than target
    if sug["donor"]["duration"] < 2.4:
        assert ext["looped"] is True


def test_place_room_tone_on_timeline(tmp_path: Path):
    wav = tmp_path / "dlg.wav"
    vid = tmp_path / "v.mp4"
    _speech_like_with_silence(wav)
    _video(vid, 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    vt = ed.add_track("video")
    ed.place_from_file(vid, "video", vt.id, 0)
    r = ed.place_room_tone(wav, gain_db=-10.0)
    assert r["clip"]["id"]
    assert r["track_id"]
    audio = [t for t in ed.project.tracks if t.kind == "audio"]
    assert audio and audio[0].clips


def test_preview_range(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _video(v, 1.2)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    ed.ensure_preview_proxy(tmp_path / "full_px.mp4", height=120, fps=8)
    seg = ed.preview_range(
        tmp_path / "seg.mp4", 0.1, 0.5, ensure_proxy=False, height=120, fps=8,
    )
    assert Path(seg["path"]).exists()
    assert seg["duration_seconds"] == 0.4
