import subprocess
from pathlib import Path

import pytest

from opmiere import Editor

FPS = 30


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    """A tiny real video file (ffmpeg required), reused read-only across tests."""
    d = tmp_path_factory.mktemp("media")
    path = d / "sample.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate={FPS}:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


@pytest.fixture
def editor(tmp_path) -> Editor:
    return Editor.create(tmp_path / "demo.opm", fps=FPS, width=160, height=90)


def test_add_track_and_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)

    assert clip.duration_frames == 30
    assert editor.duration_frames() == 30


def test_move_and_trim_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)

    editor.move_clip(clip.id, new_start=10)
    assert editor._find_clip(clip.id).start == 10

    editor.trim_clip(clip.id, src_in=5, src_out=20)
    trimmed = editor._find_clip(clip.id)
    assert (trimmed.src_in, trimmed.src_out) == (5, 20)


def test_trim_clip_rejects_invalid_range(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.trim_clip(clip.id, src_in=20, src_out=10)


def test_split_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)

    first, second = editor.split_clip(clip.id, at_frame=12)

    assert (first.start, first.src_in, first.src_out) == (0, 0, 12)
    assert (second.start, second.src_in, second.src_out) == (12, 12, 30)
    assert len(track.clips) == 2


def test_split_clip_rejects_boundary_point(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.split_clip(clip.id, at_frame=0)  # not strictly inside (0, 30)


def test_delete_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)

    deleted = editor.delete_clip(clip.id)
    assert deleted.id == clip.id
    assert editor.duration_frames() == 0
    with pytest.raises(KeyError):
        editor._find_clip(clip.id)


def test_undo_redo(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    assert editor.duration_frames() == 30

    assert editor.undo() is True  # undo add_clip
    assert editor.duration_frames() == 0
    assert editor.undo() is True  # undo add_track
    assert editor.undo() is True  # undo import_media
    assert editor.undo() is False  # nothing left

    assert editor.redo() is True  # redo import_media
    assert editor.redo() is True  # redo add_track
    assert editor.redo() is True  # redo add_clip
    assert editor.duration_frames() == 30
    assert editor.redo() is False  # nothing left


def test_failed_mutation_does_not_pollute_undo_stack(editor, sample_video):
    editor.import_media(sample_video, kind="video")
    depth_before = len(editor._undo_stack)
    with pytest.raises(KeyError):
        editor.move_clip("clp_doesnotexist", new_start=5)
    assert len(editor._undo_stack) == depth_before


def test_save_and_reopen(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.save()

    reopened = Editor.open(editor.bundle.root)
    assert reopened.duration_frames() == 30


def test_export_produces_real_file(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=20)

    out = tmp_path / "out.mp4"
    editor.export(out)
    assert out.exists() and out.stat().st_size > 0


def test_apply_effect_color(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)

    updated = editor.apply_effect(clip.id, {"type": "color", "brightness": 0.2})
    assert updated.effects == [{"type": "color", "brightness": 0.2}]


def test_apply_effect_fade(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)

    updated = editor.apply_effect(
        clip.id, {"type": "fade", "direction": "in", "duration_frames": 10}
    )
    assert updated.effects[-1]["direction"] == "in"


def test_apply_effect_rejects_unknown_type(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "chroma_key"})


def test_apply_effect_fade_rejects_bad_direction(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "fade", "direction": "sideways", "duration_frames": 5})


def test_apply_effect_fade_rejects_duration_exceeding_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "fade", "direction": "out", "duration_frames": 999})


def test_apply_effect_persists_through_save_reopen(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "color", "saturation": 0.0})
    editor.save()

    reopened = Editor.open(editor.bundle.root)
    reopened_clip = reopened._find_clip(clip.id)
    assert reopened_clip.effects == [{"type": "color", "saturation": 0.0}]


def test_export_with_effects_keeps_duration_unchanged(editor, sample_video, tmp_path):
    """Color/fade must not change how long the exported clip is."""
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "color", "contrast": 1.3})
    editor.apply_effect(clip.id, {"type": "fade", "direction": "in", "duration_frames": 5})
    editor.apply_effect(clip.id, {"type": "fade", "direction": "out", "duration_frames": 5})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05  # 30 frames @ 30fps
