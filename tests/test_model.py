import pytest

from opmiere.model import Project


def test_add_media_track_clip_and_duration():
    p = Project()
    media = p.add_media("video", "clip1.mp4", duration_frames=100, has_audio=True)
    track = p.add_track("video")
    clip = p.add_clip(track, media, start=0, src_in=10, src_out=40)

    assert clip.duration_frames == 30
    assert clip.end == 30
    assert p.duration_frames() == 30
    assert p.media_by_id(media.id) is media
    assert p.track_by_id(track.id) is track


def test_add_clip_rejects_invalid_range():
    p = Project()
    media = p.add_media("video", "clip1.mp4", duration_frames=100)
    track = p.add_track("video")
    with pytest.raises(ValueError):
        p.add_clip(track, media, start=0, src_in=40, src_out=40)  # out == in


def test_add_clip_rejects_out_of_bounds():
    p = Project()
    media = p.add_media("video", "clip1.mp4", duration_frames=50)
    track = p.add_track("video")
    with pytest.raises(ValueError):
        p.add_clip(track, media, start=0, src_in=0, src_out=999)


def test_duration_frames_across_multiple_tracks():
    p = Project()
    media = p.add_media("video", "clip1.mp4", duration_frames=200)
    v = p.add_track("video")
    a = p.add_track("audio")
    p.add_clip(v, media, start=0, src_in=0, src_out=50)
    p.add_clip(a, media, start=0, src_in=0, src_out=150)
    assert p.duration_frames() == 150


def test_project_round_trip_to_dict_from_dict():
    p = Project()
    p.timebase.fps = 24
    p.resolution.w, p.resolution.h = 1280, 720
    media = p.add_media("video", "clip1.mp4", duration_frames=100, has_audio=True)
    track = p.add_track("video")
    p.add_clip(track, media, start=0, src_in=0, src_out=50)

    restored = Project.from_dict(p.to_dict())

    assert restored.id == p.id
    assert restored.timebase.fps == 24
    assert restored.resolution.w == 1280
    assert restored.media[0].path == "clip1.mp4"
    assert restored.tracks[0].clips[0].src_in == 0
    assert restored.tracks[0].clips[0].src_out == 50
    assert restored.duration_frames() == p.duration_frames()


def test_clips_in_order_sorts_by_start():
    p = Project()
    media = p.add_media("video", "clip1.mp4", duration_frames=1000)
    track = p.add_track("video")
    late = p.add_clip(track, media, start=100, src_in=0, src_out=10)
    early = p.add_clip(track, media, start=0, src_in=0, src_out=10)
    ordered = track.clips_in_order()
    assert ordered == [early, late]
