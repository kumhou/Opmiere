"""0.1.3 editor depth: media proxy bin, transcript search, filler keep-ranges."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.filler_edit import suggest_filler_cuts_from_segments
from opmiere.render.transcript_index import search_segments

FPS = 30


def _make_video(path: Path, seconds: float = 1.0, color: str = "green") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=320x180:duration={seconds}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_media_proxy_bin_roundtrip(tmp_path: Path):
    src = tmp_path / "a.mp4"
    _make_video(src, 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=320, height=180)
    media = ed.import_media(src, "video")
    assert media.proxy_path is None

    r = ed.ensure_media_proxy(media.id, height=180)
    assert r["cache_hit"] is False
    assert Path(r["path"]).exists()
    media = ed.project.media_by_id(media.id)
    assert media.proxy_path
    assert (ed.bundle.root / media.proxy_path).exists()

    r2 = ed.ensure_media_proxy(media.id)
    assert r2["cache_hit"] is True

    bin_ = ed.list_media_bin()
    assert bin_["count"] == 1
    assert bin_["media"][0]["proxy_ready"] is True

    ed.save()
    ed2 = Editor.open(tmp_path / "p.opm")
    m2 = ed2.project.media[0]
    assert m2.proxy_path == media.proxy_path
    assert ed2.list_media_bin()["media"][0]["proxy_ready"] is True


def test_import_build_proxy(tmp_path: Path):
    src = tmp_path / "b.mp4"
    _make_video(src, 0.5, color="blue")
    ed = Editor.create(tmp_path / "q.opm", fps=FPS, width=320, height=180)
    media = ed.import_media(src, "video", build_proxy=True, proxy_height=180)
    assert media.proxy_path
    assert ed.bundle.resolve_bundle_path(media.proxy_path).exists()


def test_search_segments_keyword():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "Hello world", "words": [
            {"start": 0.0, "end": 0.4, "word": "Hello"},
            {"start": 0.5, "end": 1.0, "word": "world"},
        ]},
        {"start": 2.0, "end": 3.5, "text": "我说但是你听", "words": [
            {"start": 2.0, "end": 2.3, "word": "我"},
            {"start": 2.3, "end": 2.6, "word": "说"},
            {"start": 2.6, "end": 2.9, "word": "但是"},
            {"start": 2.9, "end": 3.5, "word": "你听"},
        ]},
    ]
    r = search_segments("但是", segs)
    assert r["hit_count"] >= 1
    assert any("但是" in (h.get("text") or "") for h in r["hits"])
    tops = r["hits"][0]
    assert tops["start"] == 2.0


def test_transcript_cache_and_search(tmp_path: Path):
    src = tmp_path / "t.mp4"
    _make_video(src, 0.4)
    ed = Editor.create(tmp_path / "tr.opm", fps=FPS, width=320, height=180)
    media = ed.import_media(src, "video")
    fake = {
        "path": str(src),
        "language": "zh",
        "duration_seconds": 0.4,
        "segments": [
            {"start": 0.0, "end": 0.4, "text": "我说但是可以", "words": [
                {"start": 0.0, "end": 0.1, "word": "我"},
                {"start": 0.1, "end": 0.2, "word": "说"},
                {"start": 0.2, "end": 0.3, "word": "但是"},
                {"start": 0.3, "end": 0.4, "word": "可以"},
            ]},
        ],
    }
    ed.cache_transcript(media.id, fake)
    hit = ed.search_transcripts("但是", media_id=media.id)
    assert hit["hit_count"] >= 1
    all_hit = ed.search_transcripts("但是")
    assert all_hit["hit_count"] >= 1
    assert ed.list_media_bin()["media"][0]["transcript_cached"] is True


def test_filler_suggest_and_apply_keep_ranges(tmp_path: Path):
    segs = [{
        "start": 0.0,
        "end": 3.0,
        "text": "hello um world uh yes",
        "words": [
            {"start": 0.0, "end": 0.5, "word": "hello"},
            {"start": 0.5, "end": 0.8, "word": "um"},
            {"start": 0.9, "end": 1.5, "word": "world"},
            {"start": 1.6, "end": 1.9, "word": "uh"},
            {"start": 2.0, "end": 2.8, "word": "yes"},
        ],
    }]
    plan = suggest_filler_cuts_from_segments(segs, duration_seconds=3.0)
    assert plan["cut_ranges"]
    assert any(
        "um" in " ".join(c.get("words") or []).lower()
        or "uh" in " ".join(c.get("words") or []).lower()
        for c in plan["cut_ranges"]
    )
    assert plan["keep_ranges"]
    # keep should cover non-filler islands
    assert sum(k["duration"] for k in plan["keep_ranges"]) < 3.0

    # 3s video at 30fps = 90 frames; place full clip then apply keep
    src = tmp_path / "talk.mp4"
    _make_video(src, 3.0)
    ed = Editor.create(tmp_path / "fill.opm", fps=FPS, width=320, height=180)
    media = ed.import_media(src, "video")
    tr = ed.add_track("video")
    clip = ed.add_clip(tr.id, media.id, 0, 0, media.duration_frames)
    # follower after main clip
    clip2 = ed.add_clip(tr.id, media.id, clip.end, 0, 15)

    applied = ed.apply_keep_ranges(clip.id, plan["keep_ranges"], time_unit="seconds")
    assert applied["new_clip_ids"]
    assert applied["removed_clip_id"] == clip.id
    # total timeline shorter than original 90+15
    assert ed.duration_frames() < 90 + 15
    # follower still present
    ids = {c.id for t in ed.project.tracks for c in t.clips}
    assert clip2.id in ids
    assert clip.id not in ids


def test_apply_filler_cuts_dry_run(tmp_path: Path):
    src = tmp_path / "d.mp4"
    _make_video(src, 1.0)
    ed = Editor.create(tmp_path / "dry.opm", fps=FPS, width=320, height=180)
    media = ed.import_media(src, "video")
    tr = ed.add_track("video")
    clip = ed.add_clip(tr.id, media.id, 0, 0, min(30, media.duration_frames))
    # inject cache so we don't need whisper
    ed.cache_transcript(media.id, {
        "path": str(src),
        "duration_seconds": 1.0,
        "segments": [{
            "start": 0.0, "end": 1.0, "text": "um hi",
            "words": [
                {"start": 0.0, "end": 0.3, "word": "um"},
                {"start": 0.4, "end": 0.9, "word": "hi"},
            ],
        }],
    })
    plan = ed.apply_filler_cuts(clip.id, dry_run=True)
    assert plan["applied"] is False
    assert plan.get("keep_ranges")
    # clip still one piece
    assert len(tr.clips) == 1

    out = ed.apply_filler_cuts(clip.id, dry_run=False)
    assert out["applied"] is True
    assert len(ed.project.tracks[0].clips) >= 1
