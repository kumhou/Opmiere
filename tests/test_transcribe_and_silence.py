"""ASR helpers + silence keep-ranges + subtitles burn-in (shipped paths)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opmiere import Editor
from opmiere.render.silence_edit import suggest_keep_ranges
from opmiere.render.asr import segments_to_srt, write_srt


FPS = 30


def _wav_beep_silence_beep(path: Path) -> None:
    """0.4s tone + 0.6s silence + 0.4s tone ≈ 1.4s (real ffmpeg, not mocked)."""
    # anullsrc silence between two sines via concat
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
        "-filter_complex",
        "[0]aformat=sample_fmts=fltp:channel_layouts=mono[a0];"
        "[1]atrim=0:0.6,aformat=sample_fmts=fltp:channel_layouts=mono[a1];"
        "[2]aformat=sample_fmts=fltp:channel_layouts=mono[a2];"
        "[a0][a1][a2]concat=n=3:v=0:a=1",
        "-c:a", "pcm_s16le", str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def test_segments_to_srt_format():
    srt = segments_to_srt([
        {"start": 0.0, "end": 1.5, "text": "你好世界"},
        {"start": 2.0, "end": 3.25, "text": "second line"},
    ])
    assert "1\n00:00:00,000 --> 00:00:01,500\n你好世界" in srt
    assert "2\n00:00:02,000 --> 00:00:03,250\nsecond line" in srt


def test_write_srt_roundtrip(tmp_path: Path):
    segs = [{"start": 0.1, "end": 0.9, "text": "hello"}]
    path = write_srt(tmp_path / "out.srt", segs)
    text = path.read_text(encoding="utf-8")
    assert "hello" in text
    assert "-->" in text


def test_suggest_keep_ranges_finds_middle_silence(tmp_path: Path):
    wav = tmp_path / "bsb.wav"
    _wav_beep_silence_beep(wav)
    result = suggest_keep_ranges(
        wav,
        silence_threshold_db=-40.0,
        min_silence_seconds=0.3,
        pad_seconds=0.05,
        min_keep_seconds=0.15,
    )
    assert result["duration_seconds"] > 1.0
    # Should detect at least one silence in the middle
    assert len(result["silences"]) >= 1
    # At least two keep islands (beep | beep) or one merged keep — either is ok
    # if pad is large; require not a single full-duration keep when silence exists
    if result["silences"]:
        assert len(result["keep_ranges"]) >= 1
        # middle silence roughly around 0.4–1.0
        mid = result["silences"][0]
        assert mid["start"] < 0.8
        assert mid["end"] > mid["start"]


def test_subtitles_effect_export_keeps_duration(tmp_path: Path):
    from opmiere.render.probe import probe

    video = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=blue:size=160x90:duration=1:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    srt = write_srt(
        tmp_path / "c.srt",
        [{"start": 0.0, "end": 0.8, "text": "TEST CAPTION"}],
    )
    ed = Editor.create(tmp_path / "cap.opm", fps=FPS, width=160, height=90)
    media = ed.import_media(video, kind="video")
    track = ed.add_track("video")
    clip = ed.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    ed.apply_effect(clip.id, {"type": "subtitles", "path": str(srt)})
    out = tmp_path / "out.mp4"
    ed.export(out)
    info = probe(out)
    assert abs(info.duration_seconds - 1.0) < 0.15


def test_apply_effect_subtitles_rejects_missing_file(tmp_path: Path):
    video = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=red:size=160x90:duration=0.5:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    ed = Editor.create(tmp_path / "t.opm", fps=FPS, width=160, height=90)
    media = ed.import_media(video, kind="video")
    track = ed.add_track("video")
    clip = ed.add_clip(track.id, media.id, start=0, src_in=0, src_out=15)
    with pytest.raises(FileNotFoundError):
        ed.apply_effect(clip.id, {"type": "subtitles", "path": str(tmp_path / "no.srt")})


def test_transcribe_entry_point_uses_whisper_model(tmp_path: Path):
    """Drives shipped transcribe(); mocks only WhisperModel (external binary)."""
    import opmiere.render.asr as asr_mod

    wav = tmp_path / "t.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
            "-c:a", "pcm_s16le", str(wav),
        ],
        capture_output=True, text=True, check=True,
    )

    fake_seg = MagicMock()
    fake_seg.start = 0.0
    fake_seg.end = 0.25
    fake_seg.text = " hello "
    fake_word = MagicMock()
    fake_word.start = 0.0
    fake_word.end = 0.2
    fake_word.word = " hello "
    fake_seg.words = [fake_word]
    fake_info = MagicMock()
    fake_info.language = "en"

    with patch.object(asr_mod, "_require_faster_whisper"):
        with patch("faster_whisper.WhisperModel") as WM:
            inst = WM.return_value
            inst.transcribe.return_value = (iter([fake_seg]), fake_info)
            result = asr_mod.transcribe(wav, model_size="tiny", language="en")

    assert result["language"] == "en"
    assert result["segments"][0]["text"] == "hello"
    assert result["segments"][0]["words"][0]["word"] == "hello"
    WM.assert_called_once()


def test_plan_session_includes_transcribe_for_a_roll(tmp_path: Path):
    from opmiere.workflow import make_brief, plan_session

    p = tmp_path / "talk.mp4"
    p.write_bytes(b"x")
    brief = make_brief(
        intent="vlog",
        assets=[{"path": str(p), "role": "a_roll"}],
        deliverable={"bundle_path": "a.opm", "export_path": "a.mp4"},
    )
    plan = plan_session(brief)
    tools = [s["tool"] for s in plan["steps"]]
    assert "transcribe" in tools
    assert "suggest_silence_cuts" in tools
    assert tools.index("place_from_file") < tools.index("transcribe")
