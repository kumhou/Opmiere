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


@pytest.fixture(scope="module")
def blue_video(tmp_path_factory) -> Path:
    """Solid blue background clip, for real chroma-key compositing tests."""
    d = tmp_path_factory.mktemp("media")
    path = d / "blue.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:size=160x90:duration=2:rate={FPS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


@pytest.fixture(scope="module")
def greenscreen_video(tmp_path_factory) -> Path:
    """Green background with a red box "subject" - a synthetic greenscreen clip."""
    d = tmp_path_factory.mktemp("media")
    path = d / "green.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=green:size=160x90:duration=2:rate={FPS},drawbox=x=55:y=35:w=50:h=25:color=red:t=fill",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


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
        editor.apply_effect(clip.id, {"type": "not_a_real_effect"})


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


def test_every_known_transition_type_maps_to_a_real_xfade_name():
    """model.KNOWN_TRANSITION_TYPES and ffmpeg.py's xfade mapping must stay in
    lockstep - an entry in one without the other either can't be used
    (validated but unmapped -> KeyError at render time) or renders silently
    as ffmpeg's default 'fade' (mapped but unvalidated -> add_transition
    would reject it before it ever reaches render, so that direction is
    already safe; this test covers the direction that isn't)."""
    from opmiere.model import KNOWN_TRANSITION_TYPES
    from opmiere.render.ffmpeg import _XFADE_TRANSITION_BY_TYPE

    assert set(_XFADE_TRANSITION_BY_TYPE) == KNOWN_TRANSITION_TYPES


def test_export_with_wipe_transition_real_render(editor, sample_video, tmp_path):
    """A non-dissolve xfade name (wipe_left) must actually render - the
    dissolve case (test_export_with_transition_real_crossfade) doesn't prove
    every entry in _XFADE_TRANSITION_BY_TYPE is a real, working ffmpeg value."""
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    clip_b = editor.add_clip(track.id, media.id, start=30, src_in=0, src_out=30)
    editor.add_transition(clip_b.id, "wipe_left", duration_frames=10)

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    expected = (30 + 30 - 10) / FPS
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


def test_apply_effect_blur_and_vignette(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "blur", "amount": 8.0})
    editor.apply_effect(clip.id, {"type": "vignette", "strength": 2.0})
    assert clip.effects[0] == {"type": "blur", "amount": 8.0}
    assert clip.effects[1] == {"type": "vignette", "strength": 2.0}


def test_apply_effect_blur_rejects_non_positive_amount(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "blur", "amount": -1})


def test_export_with_blur_and_vignette_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "blur", "amount": 6.0})
    editor.apply_effect(clip.id, {"type": "vignette"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_apply_effect_sharpen_and_film_grain(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "sharpen", "amount": 3.0})
    editor.apply_effect(clip.id, {"type": "film_grain", "amount": 40.0})
    assert clip.effects[0] == {"type": "sharpen", "amount": 3.0}
    assert clip.effects[1] == {"type": "film_grain", "amount": 40.0}


def test_apply_effect_sharpen_rejects_out_of_range_amount(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "sharpen", "amount": 8.0})  # > ffmpeg's 5 max


def test_apply_effect_film_grain_rejects_out_of_range_amount(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "film_grain", "amount": 0})


def test_export_with_sharpen_and_film_grain_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "sharpen"})
    editor.apply_effect(clip.id, {"type": "film_grain"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_apply_effect_glow(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "glow", "amount": 10.0, "intensity": 0.8})
    assert clip.effects[0] == {"type": "glow", "amount": 10.0, "intensity": 0.8}


def test_apply_effect_glow_rejects_out_of_range(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "glow", "amount": 0})
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "glow", "intensity": 1.5})


def test_export_with_glow_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "glow"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_glow_halos_bright_areas_into_dark_neighbors(tmp_path):
    """Real-pixel proof: a white box on black gets a bright halo under glow.

    Without glow, a pixel just outside the box is pure black. With glow
    (blur + screen-blend of a copy), that same pixel must lighten — the
    whole reason glow is multi-stage rather than a single linear filter.
    """
    from PIL import Image

    src = tmp_path / "whitebox.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=black:size=160x90:duration=1:rate={FPS},"
                  f"drawbox=x=60:y=30:w=40:h=30:color=white:t=fill",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ],
        capture_output=True, text=True, check=True,
    )

    def _export_frame(with_glow: bool) -> Path:
        ed = Editor.create(tmp_path / f"{'glow' if with_glow else 'plain'}.opm",
                           fps=FPS, width=160, height=90)
        media = ed.import_media(src, kind="video")
        track = ed.add_track("video")
        clip = ed.add_clip(track.id, media.id, start=0, src_in=0, src_out=15)
        if with_glow:
            ed.apply_effect(clip.id, {"type": "glow", "amount": 8.0, "intensity": 0.9})
        out = tmp_path / f"{'glow' if with_glow else 'plain'}.mp4"
        ed.export(out)
        frame = tmp_path / f"{'glow' if with_glow else 'plain'}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", "-update", "1", str(frame)],
            capture_output=True, text=True, check=True,
        )
        return frame

    plain = Image.open(_export_frame(False)).load()
    glowed = Image.open(_export_frame(True)).load()

    # Just left of the white box (box starts at x=60): plain must be near-black,
    # glow must spill light into that pixel.
    px_plain = plain[55, 45]
    px_glow = glowed[55, 45]
    assert max(px_plain) < 15, f"plain neighbor should be black, got {px_plain}"
    assert sum(px_glow) > sum(px_plain) + 30, (
        f"glow should lighten the neighbor of a bright area: plain={px_plain} glow={px_glow}"
    )
    # Far corner stays dark either way (no light to bloom from).
    assert max(glowed[5, 5]) < 25, f"far field should stay dark under glow, got {glowed[5, 5]}"
    # Center of the white box stays bright.
    assert min(glowed[80, 45]) > 200, f"box center should stay bright, got {glowed[80, 45]}"


def _write_boost_red_cube(path: Path) -> None:
    """Minimal 2³ .cube that maps pure blue → near-black and pure red → red.

    Enough structure for lut3d to load and for a solid-blue source to measurably
    darken (proves the LUT ran, not a no-op path).
    """
    # Domain [0,1], size 2. Points ordered R-fastest then G then B (Adobe cube).
    # Boost red channel: out_r = min(1, in_r + 0.5), out_g=in_g, out_b=in_b*0.2
    lines = ["TITLE \"opmiere_test_boost_red\"", "LUT_3D_SIZE 2"]
    for b in (0.0, 1.0):
        for g in (0.0, 1.0):
            for r in (0.0, 1.0):
                lines.append(f"{min(1.0, r + 0.5):.6f} {g:.6f} {b * 0.2:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_apply_effect_lut3d(editor, sample_video, tmp_path):
    cube = tmp_path / "grade.cube"
    _write_boost_red_cube(cube)
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "lut3d", "path": str(cube)})
    assert clip.effects[0]["type"] == "lut3d"
    assert clip.effects[0]["path"] == str(cube)


def test_apply_effect_lut3d_rejects_missing_path(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(FileNotFoundError):
        editor.apply_effect(clip.id, {"type": "lut3d", "path": str(tmp_path / "nope.cube")})


def test_lut3d_changes_solid_blue_pixels(tmp_path):
    """Real-pixel: a solid blue clip under a blue-crushing LUT must darken."""
    from PIL import Image

    cube = tmp_path / "crush_blue.cube"
    _write_boost_red_cube(cube)
    src = tmp_path / "blue.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=blue:size=160x90:duration=1:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ],
        capture_output=True, text=True, check=True,
    )
    ed = Editor.create(tmp_path / "lut.opm", fps=FPS, width=160, height=90)
    media = ed.import_media(src, kind="video")
    track = ed.add_track("video")
    clip = ed.add_clip(track.id, media.id, start=0, src_in=0, src_out=15)
    ed.apply_effect(clip.id, {"type": "lut3d", "path": str(cube)})
    out = tmp_path / "out.mp4"
    ed.export(out)
    frame = tmp_path / "out.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", "-update", "1", str(frame)],
        capture_output=True, text=True, check=True,
    )
    px = Image.open(frame).load()[80, 45]
    # Pure blue ~ (0,0,255); after b*0.2 LUT blue channel should drop hard.
    assert px[2] < 80, f"blue channel should be crushed by LUT, got {px}"


def test_apply_effect_shape_mask(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "shape_mask", "shape": "circle", "size": 0.4})
    assert clip.effects[0]["type"] == "shape_mask"


def test_apply_effect_shape_mask_rejects_bad_shape(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "shape_mask", "shape": "hexagon"})


def test_shape_mask_circle_composites_over_blue(tmp_path):
    """Real-pixel: red circle mask over blue base → red center, blue corners."""
    from PIL import Image

    blue = tmp_path / "blue.mp4"
    red = tmp_path / "red.mp4"
    for path, color in ((blue, "blue"), (red, "red")):
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c={color}:size=160x90:duration=1:rate={FPS}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
            ],
            capture_output=True, text=True, check=True,
        )
    ed = Editor.create(tmp_path / "mask.opm", fps=FPS, width=160, height=90)
    mb = ed.import_media(blue, kind="video")
    mr = ed.import_media(red, kind="video")
    base = ed.add_track("video")
    over = ed.add_track("video")
    ed.add_clip(base.id, mb.id, start=0, src_in=0, src_out=15)
    c = ed.add_clip(over.id, mr.id, start=0, src_in=0, src_out=15)
    ed.apply_effect(c.id, {"type": "shape_mask", "shape": "circle", "size": 0.45, "feather": 0.0})
    out = tmp_path / "out.mp4"
    ed.export(out)
    frame = tmp_path / "out.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", "-update", "1", str(frame)],
        capture_output=True, text=True, check=True,
    )
    px = Image.open(frame).load()
    center, corner = px[80, 45], px[5, 5]
    assert center[0] > center[2] + 40, f"center should be red-dominant, got {center}"
    assert corner[2] > corner[0] + 40, f"corner should be blue-dominant, got {corner}"


def test_place_after_with_transition(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    c1 = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    c2 = editor.place_after(
        c1.id, media.id, src_in=0, src_out=30,
        transition_type="cross_dissolve", transition_frames=8,
    )
    assert c2.start == 30 - 8
    assert c2.transition_in == {"type": "cross_dissolve", "duration_frames": 8}


def test_apply_effect_white_balance(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "white_balance", "temperature": 4500, "mix": 0.8})
    assert clip.effects[0] == {"type": "white_balance", "temperature": 4500, "mix": 0.8}


def test_apply_effect_white_balance_rejects_out_of_range(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "white_balance", "temperature": 500})
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "white_balance", "mix": 1.5})


def test_white_balance_warms_neutral_gray(tmp_path):
    """Real-pixel: cooling a mid-gray source must raise the blue channel relative to red."""
    from PIL import Image

    src = tmp_path / "gray.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x808080:size=160x90:duration=1:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ],
        capture_output=True, text=True, check=True,
    )

    def _frame(temp: int) -> tuple:
        ed = Editor.create(tmp_path / f"wb_{temp}.opm", fps=FPS, width=160, height=90)
        media = ed.import_media(src, kind="video")
        track = ed.add_track("video")
        clip = ed.add_clip(track.id, media.id, start=0, src_in=0, src_out=15)
        ed.apply_effect(clip.id, {"type": "white_balance", "temperature": temp, "mix": 1.0})
        out = tmp_path / f"wb_{temp}.mp4"
        ed.export(out)
        frame = tmp_path / f"wb_{temp}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", "-update", "1", str(frame)],
            capture_output=True, text=True, check=True,
        )
        return Image.open(frame).load()[80, 45]

    warm = _frame(3200)   # tungsten-ish
    cool = _frame(9000)   # blue sky-ish
    # Cool grade should be bluer (higher B relative to R) than the warm grade.
    warm_rb = warm[0] - warm[2]
    cool_rb = cool[0] - cool[2]
    assert cool_rb < warm_rb - 10, (
        f"cool temp should shift toward blue vs warm: warm={warm} cool={cool}"
    )


def test_apply_effect_ken_burns(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(
        clip.id,
        {"type": "ken_burns", "zoom_start": 1.0, "zoom_end": 1.5, "x_start": 0.0, "x_end": 1.0},
    )
    assert clip.effects[0]["type"] == "ken_burns"
    assert clip.effects[0]["zoom_end"] == 1.5


def test_apply_effect_ken_burns_rejects_zoom_below_one(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "ken_burns", "zoom_start": 0.5})


def test_ken_burns_animated_zoom_and_duration_safe(tmp_path):
    """Animated zoom is real (white box grows) and duration stays input-bounded.

    Guards the bomb: zoompan followed by scale/pad produced 512s from 1s.
    """
    from PIL import Image
    from opmiere.render.probe import probe

    src = tmp_path / "box.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=black:size=160x90:duration=1:rate={FPS},"
                  f"drawbox=x=60:y=30:w=40:h=30:color=white:t=fill",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ],
        capture_output=True, text=True, check=True,
    )

    def _export(name: str, multi: bool) -> Path:
        ed = Editor.create(tmp_path / f"{name}.opm", fps=FPS, width=160, height=90)
        media = ed.import_media(src, kind="video")
        track = ed.add_track("video")
        c1 = ed.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
        target = c1
        if multi:
            target = ed.place_after(c1.id, media.id, src_in=0, src_out=30)
        ed.apply_effect(
            target.id,
            {"type": "ken_burns", "zoom_start": 1.0, "zoom_end": 2.0,
             "x_start": 0.5, "y_start": 0.5, "x_end": 0.5, "y_end": 0.5},
        )
        out = tmp_path / f"{name}.mp4"
        ed.export(out)
        return out

    single = _export("kb_single", multi=False)
    info = probe(single)
    assert abs(info.duration_seconds - 1.0) < 0.15, info.duration_seconds

    first, last = tmp_path / "k0.png", tmp_path / "k29.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(single), "-vf", "select=eq(n\\,0)", "-frames:v", "1",
         "-update", "1", str(first)],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(single), "-vf", "select=eq(n\\,29)", "-frames:v", "1",
         "-update", "1", str(last)],
        capture_output=True, text=True, check=True,
    )

    def white_count(png: Path) -> int:
        px = Image.open(png).load()
        return sum(1 for y in range(90) for x in range(160) if sum(px[x, y]) > 600)

    w0, w1 = white_count(first), white_count(last)
    assert w1 > w0 + 200, f"zoom should grow white box: frame0={w0} frame29={w1}"

    multi = _export("kb_multi", multi=True)
    minfo = probe(multi)
    assert minfo.duration_seconds < 3.0, f"multi-clip ken_burns duration bomb: {minfo.duration_seconds}s"


def test_apply_effect_compression_and_noise_reduction(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "compression", "ratio": 8.0, "threshold_db": -24.0})
    editor.apply_effect(clip.id, {"type": "noise_reduction", "amount": 20.0})
    assert clip.effects[0] == {"type": "compression", "ratio": 8.0, "threshold_db": -24.0}
    assert clip.effects[1] == {"type": "noise_reduction", "amount": 20.0}


def test_apply_effect_compression_rejects_out_of_range_ratio(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "compression", "ratio": 25.0})  # > ffmpeg's 20 max


def test_apply_effect_noise_reduction_rejects_out_of_range_amount(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "noise_reduction", "amount": 0.0})  # < ffmpeg's 0.01 min


def test_export_with_compression_and_noise_reduction_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "compression"})
    editor.apply_effect(clip.id, {"type": "noise_reduction"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_apply_effect_audio_eq(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    updated = editor.apply_effect(clip.id, {"type": "audio_eq", "frequency_hz": 1000.0, "gain_db": -12.0})
    assert updated.effects == [{"type": "audio_eq", "frequency_hz": 1000.0, "gain_db": -12.0}]


def test_apply_effect_audio_eq_requires_frequency(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "audio_eq", "gain_db": 6.0})


def test_apply_effect_audio_eq_rejects_out_of_range_gain(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "audio_eq", "frequency_hz": 1000.0, "gain_db": 40.0})


def test_export_with_audio_eq_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "audio_eq", "frequency_hz": 440.0, "gain_db": 6.0})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


def test_apply_effect_text_accepts_border(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    updated = editor.apply_effect(
        clip.id, {"type": "text", "content": "hi", "border_width": 4, "border_color": "red"})
    assert updated.effects[-1]["border_width"] == 4


def test_apply_effect_text_rejects_negative_border(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "text", "content": "hi", "border_width": -1})


def test_text_effect_renders_border_into_drawtext(tmp_path):
    from opmiere.render.ffmpeg import _effect_filters
    explicit = _effect_filters(
        [{"type": "text", "content": "hi", "border_width": 3, "border_color": "navy"}],
        clip_duration_frames=30, fps=30, stream="video", text_dir=tmp_path)
    dt = next(p for p in explicit if p.startswith("drawtext"))
    assert "borderw=3" in dt and "bordercolor=navy" in dt
    # default border is applied when unspecified (captions need it by default)
    default = _effect_filters(
        [{"type": "text", "content": "hi"}],
        clip_duration_frames=30, fps=30, stream="video", text_dir=tmp_path)
    assert "borderw=2" in next(p for p in default if p.startswith("drawtext"))


def test_second_video_track_is_a_gapped_overlay_layer(editor, sample_video, tmp_path):
    """Real render: base track (2s) + a second video track with a clip that
    only covers part of that span. Total duration must follow the base
    track (overlay tracks are allowed gaps), and the export must not error
    just because a second video track has a shorter/partial clip."""
    media = editor.import_media(sample_video, kind="video")
    base = editor.add_track("video")
    overlay = editor.add_track("video")
    editor.add_clip(base.id, media.id, start=0, src_in=0, src_out=60)  # full 2s base
    editor.add_clip(overlay.id, media.id, start=20, src_in=0, src_out=20)  # overlay covers frames 20-40 only

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 2.0) < 0.05  # driven by the base track, not the overlay


def test_overlapping_clips_on_same_overlay_track_rejected(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    base = editor.add_track("video")
    overlay = editor.add_track("video")
    editor.add_clip(base.id, media.id, start=0, src_in=0, src_out=60)
    editor.add_clip(overlay.id, media.id, start=0, src_in=0, src_out=20)
    editor.add_clip(overlay.id, media.id, start=10, src_in=0, src_out=20)  # overlaps the first overlay clip

    with pytest.raises(ValueError, match="overlapping"):
        editor.export(tmp_path / "out.mp4")


def test_apply_effect_chroma_key_rejects_bad_similarity(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "chroma_key", "similarity": 1.5})
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "chroma_key", "blend": -0.1})


def test_chroma_key_composites_transparently_over_base_track(editor, blue_video, greenscreen_video, tmp_path):
    """Real render: blue base track + a greenscreen overlay clip with
    chroma_key applied. The composited output must show blue where the
    overlay clip was green, and the red "subject" box unaffected - proof
    the alpha this produces actually survives scale/pad/overlay, not just
    that ffmpeg didn't error."""
    blue = editor.import_media(blue_video, kind="video")
    green = editor.import_media(greenscreen_video, kind="video")
    base = editor.add_track("video")
    overlay = editor.add_track("video")
    editor.add_clip(base.id, blue.id, start=0, src_in=0, src_out=60)
    clip = editor.add_clip(overlay.id, green.id, start=0, src_in=0, src_out=60)
    editor.apply_effect(clip.id, {"type": "chroma_key"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-vf", "select=eq(n\\,15)", "-update", "1",
         "-vframes", "1", str(frame_path)],
        capture_output=True, text=True, check=True,
    )
    # Sample a corner pixel (should be the blue background showing through
    # where the greenscreen was keyed out) and the center pixel (the red box).
    from PIL import Image
    img = Image.open(frame_path).convert("RGB")
    corner = img.getpixel((5, 5))
    center = img.getpixel((80, 45))
    assert corner[2] > corner[0] and corner[2] > corner[1]  # blue dominant, not green
    assert center[0] > center[1] and center[0] > center[2]  # red dominant


@pytest.fixture(scope="module")
def white_video(tmp_path_factory) -> Path:
    """White background with a black box "subject" - for luma_key tests."""
    d = tmp_path_factory.mktemp("media")
    path = d / "white.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=white:size=160x90:duration=2:rate={FPS},drawbox=x=55:y=30:w=50:h=30:color=black:t=fill",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


def test_apply_effect_luma_key_rejects_bad_threshold(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "luma_key", "threshold": 1.5})


def test_luma_key_composites_transparently_over_base_track(editor, blue_video, white_video, tmp_path):
    """Real render: blue base + a white-background overlay clip with
    luma_key applied. White should key transparent (showing blue through),
    the black box should survive (low luma, below threshold)."""
    blue = editor.import_media(blue_video, kind="video")
    white = editor.import_media(white_video, kind="video")
    base = editor.add_track("video")
    overlay = editor.add_track("video")
    editor.add_clip(base.id, blue.id, start=0, src_in=0, src_out=60)
    clip = editor.add_clip(overlay.id, white.id, start=0, src_in=0, src_out=60)
    editor.apply_effect(clip.id, {"type": "luma_key", "threshold": 0.9, "tolerance": 0.1})

    out = tmp_path / "out.mp4"
    editor.export(out)

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-vf", "select=eq(n\\,15)", "-update", "1",
         "-vframes", "1", str(frame_path)],
        capture_output=True, text=True, check=True,
    )
    from PIL import Image
    img = Image.open(frame_path).convert("RGB")
    corner = img.getpixel((5, 5))  # was white - should show blue background
    center = img.getpixel((80, 45))  # the black box - should survive, near-black
    assert corner[2] > corner[0] and corner[2] > corner[1]
    assert sum(center) < 60  # near-black, not keyed out


def test_apply_effect_curves_rejects_unknown_preset(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "curves", "preset": "not_a_real_preset"})


def test_export_with_curves_preset_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "curves", "preset": "vintage"})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


@pytest.fixture(scope="module")
def split_color_video(tmp_path_factory) -> Path:
    """Left half red, right half blue - for crop precision tests."""
    d = tmp_path_factory.mktemp("media")
    path = d / "split.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=red:size=40x80:duration=1:rate={FPS}[l];"
              f"color=c=blue:size=40x80:duration=1:rate={FPS}[r];[l][r]hstack",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


def test_apply_effect_crop_rejects_bad_dimensions(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "crop", "width": -1, "height": 10})
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "crop", "width": 10})  # missing height


def test_crop_keeps_only_the_requested_region(split_color_video, tmp_path):
    # Project canvas matches the post-crop aspect ratio exactly (40x80), so
    # the fit-to-canvas scale/pad step downstream doesn't letterbox the
    # result - otherwise sampled pixels could land in a black pad bar
    # instead of the actual cropped content.
    editor = Editor.create(tmp_path / "crop_demo.opm", fps=FPS, width=40, height=80)
    media = editor.import_media(split_color_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=25)
    editor.apply_effect(clip.id, {"type": "crop", "width": 40, "height": 80, "x": 0, "y": 0})

    out = tmp_path / "out.mp4"
    editor.export(out)

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-vf", "select=eq(n\\,10)", "-update", "1",
         "-vframes", "1", str(frame_path)],
        capture_output=True, text=True, check=True,
    )
    from PIL import Image
    img = Image.open(frame_path).convert("RGB")
    left = img.getpixel((5, 40))
    right = img.getpixel((img.width - 5, 40))
    # Cropped to the left (red) half only - no blue should have survived anywhere.
    assert left[0] > left[2]
    assert right[0] > right[2]


def test_apply_effect_rotate_rejects_non_numeric_degrees(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.apply_effect(clip.id, {"type": "rotate", "degrees": "not a number"})


def test_export_with_rotate_keeps_duration_unchanged(editor, sample_video, tmp_path):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.apply_effect(clip.id, {"type": "rotate", "degrees": 45})

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05


@pytest.fixture(scope="module")
def red_video(tmp_path_factory) -> Path:
    """Solid red foreground clip, for picture-in-picture position tests."""
    d = tmp_path_factory.mktemp("media")
    path = d / "red.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=red:size=160x90:duration=2:rate={FPS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


def test_set_position_rejects_out_of_range_values(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    with pytest.raises(ValueError):
        editor.set_position(clip.id, x=0.5, y=0.5, scale=1.5)  # scale out of (0, 1]
    with pytest.raises(ValueError):
        editor.set_position(clip.id, x=1.1, y=0.5, scale=0.5)  # x out of [0, 1]
    with pytest.raises(ValueError):
        editor.set_position(clip.id, x=0.5, y=0.5, scale=0.0)  # scale must be > 0


def test_clear_position_restores_full_frame(editor, sample_video):
    media = editor.import_media(sample_video, kind="video")
    track = editor.add_track("video")
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=30)
    editor.set_position(clip.id, x=1.0, y=1.0, scale=0.25)
    assert clip.position is not None
    editor.clear_position(clip.id)
    assert clip.position is None


def test_set_position_renders_a_pip_box_in_the_requested_corner(editor, blue_video, red_video, tmp_path):
    """Real render: blue base track (160x90) + a red overlay clip pinned to
    the bottom-right corner at half size via set_position(x=1, y=1,
    scale=0.5). The box should be exactly 80x45 flush against the
    bottom-right edge - blue everywhere else, red only inside that box."""
    blue = editor.import_media(blue_video, kind="video")
    red = editor.import_media(red_video, kind="video")
    base = editor.add_track("video")
    overlay = editor.add_track("video")
    editor.add_clip(base.id, blue.id, start=0, src_in=0, src_out=60)
    clip = editor.add_clip(overlay.id, red.id, start=0, src_in=0, src_out=60)
    editor.set_position(clip.id, x=1.0, y=1.0, scale=0.5)

    out = tmp_path / "out.mp4"
    editor.export(out)

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-vf", "select=eq(n\\,15)", "-update", "1",
         "-vframes", "1", str(frame_path)],
        capture_output=True, text=True, check=True,
    )
    from PIL import Image
    img = Image.open(frame_path).convert("RGB")
    top_left = img.getpixel((5, 5))  # outside the box - must stay blue
    inside_box = img.getpixel((150, 85))  # bottom-right corner - inside the box
    just_outside_box_left = img.getpixel((75, 85))  # left of the 80px-wide box - must stay blue
    assert top_left[2] > top_left[0]  # blue dominant
    assert inside_box[0] > inside_box[2]  # red dominant
    assert just_outside_box_left[2] > just_outside_box_left[0]  # blue dominant
