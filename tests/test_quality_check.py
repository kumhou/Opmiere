"""Real ffmpeg-backed tests for render.quality_check - synthetic clips with
known, deliberate defects (black/frozen/blurry/silent), not mocks, since the
whole point is verifying ffmpeg's own filters actually catch what they claim to.
"""

import subprocess
from pathlib import Path

import pytest

from opmiere.render.quality_check import quality_check

FPS = 25


def _make(tmp_path_factory, name: str, vf: str | None, af: str | None, video_src: str,
          audio_src: str | None = None) -> Path:
    d = tmp_path_factory.mktemp("qc_media")
    path = d / name
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", video_src]
    if audio_src:
        cmd += ["-f", "lavfi", "-i", audio_src]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_src:
        cmd += ["-c:a", "aac"]
    cmd.append(str(path))
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


@pytest.fixture(scope="module")
def clean_clip(tmp_path_factory) -> Path:
    return _make(tmp_path_factory, "clean.mp4", None, None,
                 f"testsrc2=size=320x240:rate={FPS}:duration=3",
                 "sine=frequency=440:duration=3")


@pytest.fixture(scope="module")
def black_clip(tmp_path_factory) -> Path:
    return _make(tmp_path_factory, "black.mp4", None, None,
                 f"color=c=black:size=320x240:rate={FPS}:duration=3")


@pytest.fixture(scope="module")
def static_clip(tmp_path_factory) -> Path:
    return _make(tmp_path_factory, "static.mp4", None, None,
                 f"color=c=red:size=320x240:rate={FPS}:duration=3")


@pytest.fixture(scope="module")
def blurry_clip(tmp_path_factory) -> Path:
    return _make(tmp_path_factory, "blurry.mp4", "gblur=sigma=20", None,
                 f"testsrc2=size=320x240:rate={FPS}:duration=3")


@pytest.fixture(scope="module")
def silent_av_clip(tmp_path_factory) -> Path:
    return _make(tmp_path_factory, "silent.mp4", None, None,
                 f"testsrc2=size=320x240:rate={FPS}:duration=3", "anullsrc=duration=3")


def test_clean_clip_passes(clean_clip):
    result = quality_check(clean_clip)
    assert result.passed
    assert result.issues == []
    assert result.is_blurry is False
    assert result.is_silent is False


def test_black_clip_flagged(black_clip):
    result = quality_check(black_clip)
    assert not result.passed
    assert result.is_black
    assert result.is_static  # a solid black frame is also, correctly, "frozen"


def test_static_clip_flagged(static_clip):
    result = quality_check(static_clip)
    assert not result.passed
    assert result.is_static
    assert not result.is_black  # red, not black - a distinct failure mode


def test_blurry_clip_flagged(blurry_clip):
    result = quality_check(blurry_clip)
    assert not result.passed
    assert result.is_blurry
    assert result.blur_score is not None and result.blur_score > 30.0


def test_silent_clip_flagged(silent_av_clip):
    result = quality_check(silent_av_clip)
    assert not result.passed
    assert result.is_silent


def test_video_only_file_reports_none_for_silence(black_clip):
    result = quality_check(black_clip)
    assert result.is_silent is None


def test_editor_quality_check_matches_module_function(clean_clip):
    from opmiere import Editor
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        editor = Editor.create(Path(d) / "demo.opm", fps=FPS, width=320, height=240)
        result = editor.quality_check(clean_clip)
        assert result["passed"] is True
