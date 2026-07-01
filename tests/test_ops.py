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


def test_apply_effect_gain(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    updated = editor.apply_effect(clip.id, {"type": "gain", "db": -6.0})
    assert updated.effects == [{"type": "gain", "db": -6.0}]


def test_apply_effect_gain_rejects_non_numeric_db(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "gain", "db": "loud"})


def test_apply_effect_text(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    updated = editor.apply_effect(clip.id, {"type": "text", "content": "你好 Opmiere"})
    assert updated.effects[-1]["content"] == "你好 Opmiere"


def test_apply_effect_text_rejects_empty_content(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "text", "content": "   "})


def test_apply_effect_text_rejects_bad_position(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "text", "content": "hi", "position": "middle-ish"})


def test_export_with_gain_and_text_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "gain", "db": 3.0})
    editor.apply_effect(clip.id, {"type": "text", "content": "你好 Opmiere: test's"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_add_transition_shifts_clip_start_and_declares_it(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip_a = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    clip_b = editor.add_clip(track.id, media.id, start=30, src_in=0, src_out=30)

    updated_b = editor.add_transition(clip_b.id, "cross_dissolve", duration_frames=10)

    assert updated_b.start == 20  # 30 - 10
    assert updated_b.transition_in == {"type": "cross_dissolve", "duration_frames": 10}
    # total timeline shrinks by the overlap
    assert editor.duration_frames() == clip_a.duration_frames + clip_b.duration_frames - 10


def test_add_transition_rejects_on_first_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip_a = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.add_transition(clip_a.id, "cross_dissolve", duration_frames=5)


def test_add_transition_rejects_unknown_type(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    clip_b = editor.add_clip(track.id, media.id, start=30, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.add_transition(clip_b.id, "star_wipe", duration_frames=5)


def test_add_transition_rejects_duration_exceeding_shorter_clip(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=10)  # short clip
    clip_b = editor.add_clip(track.id, media.id, start=10, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.add_transition(clip_b.id, "cross_dissolve", duration_frames=20)  # > clip_a's 10


def test_add_transition_rejects_non_clean_cut(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    clip_b = editor.add_clip(track.id, media.id, start=30, src_in=0, src_out=30)
    editor.move_clip(clip_b.id, new_start=40)  # introduces a gap
    with pytest.raises(ValueError):
        editor.add_transition(clip_b.id, "cross_dissolve", duration_frames=5)


def test_remove_transition_restores_start(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    clip_b = editor.add_clip(track.id, media.id, start=30, src_in=0, src_out=30)
    editor.add_transition(clip_b.id, "cross_dissolve", duration_frames=10)

    restored = editor.remove_transition(clip_b.id)
    assert restored.start == 30
    assert restored.transition_in is None


def test_remove_transition_rejects_when_none_present(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip_a = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.remove_transition(clip_a.id)


def test_export_with_transition_real_crossfade(editor, sample_video, tmp_path):
    """Real render: duration must shrink by exactly the transition overlap."""
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)  # 1.0s
    clip_b = editor.add_clip(track.id, media.id, start=30, src_in=0, src_out=30)  # 1.0s
    editor.add_transition(clip_b.id, "cross_dissolve", duration_frames=10)  # 1/3s overlap

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    expected = (30 + 30 - 10) / FPS  # 50 frames @ 30fps = 1.667s
    assert abs(result.duration_seconds - expected) < 0.05


def test_set_speed_changes_timeline_duration_not_source(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=60)  # 60 source frames

    sped_up = editor.set_speed(clip.id, 2.0)
    assert sped_up.duration_frames == 60  # source frames unchanged
    assert sped_up.timeline_duration_frames == 30  # timeline footprint halved
    assert sped_up.end == 30
    assert editor.duration_frames() == 30

    slowed = editor.set_speed(clip.id, 0.5)
    assert slowed.timeline_duration_frames == 120  # timeline footprint doubled


def test_set_speed_rejects_non_positive(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.set_speed(clip.id, 0)
    with pytest.raises(ValueError):
        editor.set_speed(clip.id, -1.0)


def test_speed_persists_through_save_reopen(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.set_speed(clip.id, 1.5)
    editor.save()

    reopened = Editor.open(editor.bundle.root)
    assert reopened._find_clip(clip.id).speed == 1.5


def test_export_with_video_speed_change_real_duration(editor, sample_video, tmp_path):
    """Real render: a 2x-speed 60-frame clip must produce a 1.0s (30 frame) export."""
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=60)
    editor.set_speed(clip.id, 2.0)

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05  # 60 source frames / 2x speed / 30fps = 1.0s


def test_export_with_audio_speed_change_real_duration(editor, sample_video, tmp_path):
    """Real render: audio speed uses atempo; must also shrink actual output duration."""
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=60)
    editor.set_speed(clip.id, 1.5)

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    expected = (60 / 1.5) / FPS  # 40 frames @ 30fps = 1.333s
    assert abs(result.duration_seconds - expected) < 0.05
    assert result.has_audio


def test_set_speed_rejects_audio_out_of_atempo_range_at_render_time(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=60)
    editor.set_speed(clip.id, 3.0)  # video-only fine, but this clip has audio -> exceeds atempo's 2.0 max

    with pytest.raises(ValueError, match="atempo"):
        editor.export(tmp_path / "out.mp4")
