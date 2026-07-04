"""Audio subsystem tests: multi-track mixing, ducking, place_from_file, and
analyze_audio (the agent's "ears"). Same approach as test_ops.py's effect
tests — real ffmpeg renders measured with volumedetect, not mocked graphs."""

import re
import subprocess
from pathlib import Path

import pytest

from opmiere import Editor
from opmiere.render.probe import probe

FPS = 30


@pytest.fixture
def editor(tmp_path) -> Editor:
    return Editor.create(tmp_path / "demo.opm", fps=FPS, width=160, height=90)


@pytest.fixture(scope="module")
def music_wav(tmp_path_factory) -> Path:
    """A steady 3s 220Hz tone, standing in for a music bed."""
    d = tmp_path_factory.mktemp("media")
    path = d / "music.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
         "-ar", "48000", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


@pytest.fixture(scope="module")
def voice_wav(tmp_path_factory) -> Path:
    """A 1s 880Hz tone, standing in for one spoken line."""
    d = tmp_path_factory.mktemp("media")
    path = d / "voice.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
         "-ar", "48000", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


@pytest.fixture(scope="module")
def silent_video(tmp_path_factory) -> Path:
    """A video with no audio stream at all."""
    d = tmp_path_factory.mktemp("media")
    path = d / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=blue:size=160x90:duration=1:rate={FPS}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


def _mean_volume_db(path: Path, start_s: float, duration_s: float) -> float:
    """volumedetect's mean_volume over one window of a file."""
    proc = subprocess.run(
        ["ffmpeg", "-ss", str(start_s), "-t", str(duration_s), "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"mean_volume: (-?[\d.]+) dB", proc.stderr)
    assert m, f"no mean_volume in ffmpeg output:\n{proc.stderr}"
    return float(m.group(1))


def test_delete_track_removes_clips_and_clears_duck_references(editor, music_wav):
    music = editor.import_media(music_wav, kind="audio")
    base = editor.add_track("audio")
    overlay = editor.add_track("audio")
    editor.add_clip(base.id, music.id, start=0, src_in=0, src_out=30)
    editor.add_clip(overlay.id, music.id, start=0, src_in=0, src_out=30)
    editor.set_ducking(base.id, overlay.id)

    editor.delete_track(overlay.id)
    with pytest.raises(KeyError):
        editor.project.track_by_id(overlay.id)
    # the duck-against reference to the deleted track must not dangle
    assert editor.project.track_by_id(base.id).duck is None

    with pytest.raises(KeyError):
        editor.delete_track("trk_nope")


def test_place_from_file_uses_full_duration_by_default(editor, voice_wav):
    track = editor.add_track("audio")
    clip = editor.place_from_file(voice_wav, "audio", track.id, start=0)
    media = editor.project.media_by_id(clip.media)
    assert clip.src_in == 0
    assert clip.src_out == media.duration_frames == FPS  # the whole 1s file


def test_place_from_file_image_requires_duration(editor, tmp_path):
    png = tmp_path / "still.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:size=160x90",
         "-frames:v", "1", str(png)],
        capture_output=True, text=True, check=True,
    )
    track = editor.add_track("video")
    with pytest.raises(ValueError):
        editor.place_from_file(png, "image", track.id, start=0)
    clip = editor.place_from_file(png, "image", track.id, start=0, duration_frames=45)
    assert clip.src_out == 45


def test_set_ducking_rejects_bad_arguments(editor):
    a1 = editor.add_track("audio")
    a2 = editor.add_track("audio")
    v1 = editor.add_track("video")
    with pytest.raises(ValueError):
        editor.set_ducking(a1.id, v1.id)  # against a video track
    with pytest.raises(ValueError):
        editor.set_ducking(a1.id, a1.id)  # against itself
    with pytest.raises(ValueError):
        editor.set_ducking(a1.id, a2.id, ratio=25.0)  # ratio out of range
    with pytest.raises(KeyError):
        editor.set_ducking(a1.id, "trk_nope")
    with pytest.raises(ValueError):
        editor.clear_ducking(a1.id)  # nothing to clear


def test_ducking_survives_save_and_reload(editor):
    a1 = editor.add_track("audio")
    a2 = editor.add_track("audio")
    editor.set_ducking(a1.id, a2.id, threshold_db=-25.0, ratio=6.0)
    editor.save()
    reopened = Editor.open(editor.bundle.root)
    duck = reopened.project.track_by_id(a1.id).duck
    assert duck["against"] == a2.id
    assert duck["threshold_db"] == -25.0
    assert duck["ratio"] == 6.0


def test_export_mixes_two_audio_tracks(editor, music_wav, voice_wav, tmp_path):
    """Real render: a quiet 3s music bed plus a loud 1s voice clip placed at
    t=1s on a second audio track. The voice window of the export must be
    much louder than the music-only region - proof both tracks are actually
    in the mix at their authored levels."""
    music = editor.import_media(music_wav, kind="audio")
    voice = editor.import_media(voice_wav, kind="audio")
    base = editor.add_track("audio")
    overlay = editor.add_track("audio")
    mclip = editor.add_clip(base.id, music.id, start=0, src_in=0, src_out=3 * FPS)
    editor.apply_effect(mclip.id, {"type": "gain", "db": -15.0})
    editor.add_clip(overlay.id, voice.id, start=FPS, src_in=0, src_out=FPS)

    out = tmp_path / "mix.mp4"
    editor.export(out)

    result = probe(out)
    assert result.has_audio
    assert 2.8 < result.duration_seconds < 3.3  # full music bed, not cut at the voice

    music_only = _mean_volume_db(out, 0.2, 0.6)
    voice_window = _mean_volume_db(out, 1.1, 0.8)
    assert voice_window > music_only + 6


def test_ducking_lowers_music_under_voiceover(editor, music_wav, voice_wav, tmp_path):
    """Render the same two-track project with and without ducking. During
    the voice the ducked export must be measurably quieter (the music got
    out of the way; the voice itself is identical in both), outside the
    voice both must measure the same, and the mix must still run the full
    3s (the sidechain key is only 1s long - the apad regression guard)."""
    music = editor.import_media(music_wav, kind="audio")
    voice = editor.import_media(voice_wav, kind="audio")
    base = editor.add_track("audio")
    overlay = editor.add_track("audio")
    editor.add_clip(base.id, music.id, start=0, src_in=0, src_out=3 * FPS)
    editor.add_clip(overlay.id, voice.id, start=FPS, src_in=0, src_out=FPS)

    plain = tmp_path / "plain.mp4"
    editor.export(plain)

    editor.set_ducking(base.id, overlay.id, threshold_db=-40.0, ratio=20.0,
                       attack_ms=5.0, release_ms=100.0)
    ducked = tmp_path / "ducked.mp4"
    editor.export(ducked)

    assert 2.8 < probe(ducked).duration_seconds < 3.3

    before_plain = _mean_volume_db(plain, 0.2, 0.6)
    before_ducked = _mean_volume_db(ducked, 0.2, 0.6)
    assert abs(before_plain - before_ducked) < 1.0  # ducking idle without key signal

    during_plain = _mean_volume_db(plain, 1.15, 0.7)
    during_ducked = _mean_volume_db(ducked, 1.15, 0.7)
    assert during_ducked < during_plain - 2.0  # the music actually got out of the way


def test_export_fails_clearly_when_duck_key_track_is_empty(editor, music_wav, tmp_path):
    music = editor.import_media(music_wav, kind="audio")
    base = editor.add_track("audio")
    empty = editor.add_track("audio")
    editor.add_clip(base.id, music.id, start=0, src_in=0, src_out=FPS)
    editor.set_ducking(base.id, empty.id)
    with pytest.raises(ValueError, match="no rendered audio"):
        editor.export(tmp_path / "out.mp4")


def test_analyze_audio_reports_metrics_silences_and_image(editor, tmp_path):
    src = tmp_path / "tone_then_silence.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1,apad=pad_dur=1.5",
         "-ar", "48000", str(src)],
        capture_output=True, text=True, check=True,
    )
    img = tmp_path / "ears.png"
    report = editor.analyze_audio(src, img)

    assert report["mean_volume_db"] is not None
    assert report["max_volume_db"] is not None
    assert report["integrated_lufs"] is not None
    assert report["true_peak_dbfs"] is not None
    assert len(report["silences"]) == 1
    silence = report["silences"][0]
    assert 0.8 < silence["start_seconds"] < 1.2
    assert silence["end_seconds"] > 2.3
    assert Path(report["image_path"]).stat().st_size > 0


def test_analyze_audio_rejects_file_without_audio(editor, silent_video):
    with pytest.raises(ValueError, match="no audio stream"):
        editor.analyze_audio(silent_video)
