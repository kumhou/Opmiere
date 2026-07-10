"""import_media auto fps conform for real-world 60fps sources."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.probe import probe

FPS = 30


def _video_at_fps(path: Path, fps: float, dur: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=blue:size=160x90:duration={dur}:rate={fps}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_import_60fps_into_30_conforms(tmp_path: Path):
    src = tmp_path / "60.mp4"
    _video_at_fps(src, 60.0, dur=0.5)
    info = probe(src)
    assert info.fps and abs(info.fps - 60.0) < 1.0

    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    media = ed.import_media(src, "video", conform=True)
    assert media.origin is not None
    assert "conformed" in media.origin
    assert media.origin["conformed"]["from_fps"] >= 50
    assert media.origin["conformed"]["to_fps"] == 30.0

    bundle_file = ed.bundle.media_path(media.path)
    conf = probe(bundle_file)
    assert conf.fps and abs(conf.fps - 30.0) < 0.5
    assert media.duration_frames > 0

    tr = ed.add_track("video")
    ed.add_clip(tr.id, media.id, 0, 0, media.duration_frames)
    out = tmp_path / "out.mp4"
    ed.export(out)
    assert out.exists() and out.stat().st_size > 0


def test_import_mismatch_without_conform_raises(tmp_path: Path):
    src = tmp_path / "60.mp4"
    _video_at_fps(src, 60.0, dur=0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    try:
        ed.import_media(src, "video", conform=False)
        raised = False
    except ValueError as e:
        raised = True
        assert "does not match" in str(e) or "fps" in str(e).lower()
    assert raised


def test_matching_fps_no_conform_origin(tmp_path: Path):
    src = tmp_path / "30.mp4"
    _video_at_fps(src, 30.0, dur=0.4)
    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    media = ed.import_media(src, "video")
    assert media.origin is None or "conformed" not in (media.origin or {})


def _video_size(path: Path, size: str, fps: float = 30.0, dur: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=red:size={size}:duration={dur}:rate={fps}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_import_fit_contain_letterboxes(tmp_path: Path):
    src = tmp_path / "wide.mp4"
    _video_size(src, "320x90", fps=30.0)  # 32:9-ish strip
    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    media = ed.import_media(src, "video", fit="contain")
    assert media.origin and "conformed" in media.origin
    assert media.origin["conformed"]["fit"] == "contain"
    conf = probe(ed.bundle.media_path(media.path))
    assert conf.width == 160
    assert conf.height == 90


def test_audio_sample_rate_conform(tmp_path: Path):
    src = tmp_path / "vo44.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=0.5",
            "-ar", "44100", str(src),
        ],
        capture_output=True, text=True, check=True,
    )
    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    # project default sample_rate 48000
    media = ed.import_media(src, "audio", conform=True)
    assert media.origin and "conformed" in media.origin
    assert media.origin["conformed"].get("to_sample_rate") == 48000


def test_import_fit_cover_fills(tmp_path: Path):
    src = tmp_path / "tall.mp4"
    _video_size(src, "90x160", fps=30.0)
    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    media = ed.import_media(src, "video", fit="cover")
    conf = probe(ed.bundle.media_path(media.path))
    assert conf.width == 160
    assert conf.height == 90
    tr = ed.add_track("video")
    ed.add_clip(tr.id, media.id, 0, 0, media.duration_frames)
    out = tmp_path / "cover_out.mp4"
    ed.export(out)
    assert out.exists()
