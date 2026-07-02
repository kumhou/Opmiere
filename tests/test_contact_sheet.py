"""Real ffmpeg-backed tests for render.make_contact_sheet."""

import subprocess
from pathlib import Path

import pytest

from opmiere.render.contact_sheet import make_contact_sheet

FPS = 25


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("cs_media")
    path = d / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate={FPS}:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


@pytest.fixture(scope="module")
def audio_only(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("cs_media")
    path = d / "audio.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


def test_make_contact_sheet_writes_a_real_image(clip, tmp_path):
    out = tmp_path / "sheet.png"
    result = make_contact_sheet(clip, out, cols=3, rows=3, tile_width=120)

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0
    from PIL import Image
    img = Image.open(out)
    assert img.width == 120 * 3  # 3 tiles wide, each scaled to tile_width


def test_make_contact_sheet_creates_output_parent_dir(clip, tmp_path):
    out = tmp_path / "nested" / "dir" / "sheet.png"
    make_contact_sheet(clip, out, cols=2, rows=2)

    assert out.exists()


def test_make_contact_sheet_handles_short_clip_without_enough_frames(tmp_path):
    short = tmp_path / "short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate={FPS}:duration=0.2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(short)],
        capture_output=True, text=True, check=True,
    )
    out = tmp_path / "sheet.png"
    make_contact_sheet(short, out, cols=3, rows=3)  # fewer frames than 9 tiles - must not raise

    assert out.exists()


def test_make_contact_sheet_rejects_audio_only_file(audio_only, tmp_path):
    with pytest.raises(ValueError, match="no video stream"):
        make_contact_sheet(audio_only, tmp_path / "sheet.png")
