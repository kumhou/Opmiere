"""Loudness normalize, delivery_check, sequence contact sheet, review_cut."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.delivery import delivery_check, normalize_loudness
from opmiere.workflow import make_brief, plan_session

FPS = 30


def _color_clip(path: Path, color: str = "blue", dur: float = 0.8, size: str = "160x90") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size={size}:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _quiet_loud_wav(path: Path, *, volume: float = 0.05, dur: float = 2.0) -> None:
    """Quiet sine so normalize has headroom / work to do."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={dur},volume={volume}",
            "-ar", "48000", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_normalize_loudness_moves_toward_streaming_target(tmp_path: Path):
    src = tmp_path / "quiet.wav"
    out = tmp_path / "norm.wav"
    _quiet_loud_wav(src, volume=0.02, dur=2.5)
    report = normalize_loudness(src, out, preset="streaming", two_pass=True)
    assert out.exists()
    assert report["after"]["integrated_lufs"] is not None
    # Quiet source should land near -14 after loudnorm (tolerance generous)
    assert abs(report["after"]["integrated_lufs"] - (-14.0)) < 3.5


def test_delivery_check_flags_hot_or_wrong_geometry(tmp_path: Path):
    v = tmp_path / "v.mp4"
    _color_clip(v, dur=1.0)
    # Wrong expected size → error
    r = delivery_check(
        v,
        preset="streaming",
        expected_width=1920,
        expected_height=1080,
        expected_fps=30,
        lufs_tolerance=20.0,  # ignore loudness for this assert
        run_quality_check=True,
    )
    assert r["ok"] is False
    assert any("width" in e or "height" in e for e in r["errors"])


def test_delivery_check_passes_matching_geometry_after_normalize(tmp_path: Path):
    v = tmp_path / "v.mp4"
    n = tmp_path / "n.mp4"
    _color_clip(v, dur=1.2)
    normalize_loudness(v, n, preset="streaming", two_pass=True)
    r = delivery_check(
        n,
        preset="streaming",
        expected_width=160,
        expected_height=90,
        expected_fps=30,
        lufs_tolerance=2.5,
        run_quality_check=True,
    )
    assert r["probe"]["width"] == 160
    # loudnorm on short synthetic may still be slightly off; ok may be True or False
    # but geometry errors must be absent
    assert not any("width" in e or "height" in e for e in r["errors"])


def test_review_cut_and_sequence_sheet(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _color_clip(a, color="blue", dur=0.7)
    _color_clip(b, color="red", dur=0.7)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    plan = ed.plan_edit(
        paths=[str(a), str(b)],
        fps=FPS,
        width=160,
        height=90,
        cut_silence=False,
        prefer_scenes=False,
        transition_default="hard_cut",
        transition_frames=0,
        analyze_if_needed=True,
    )
    ed.apply_edit_plan(plan)
    rev = ed.review_cut(check_brightness_jumps=True, expect_music_duck=False)
    assert rev["base_clip_count"] >= 2
    assert rev["ok"] is True  # contiguous hard cuts

    sheet = ed.make_sequence_contact_sheet(tmp_path / "seq.png", max_tiles=8, cols=2)
    assert Path(sheet["path"]).exists()
    assert sheet["tile_count"] >= 2
    assert Path(sheet["path"]).stat().st_size > 0


def test_review_cut_flags_no_ducking(tmp_path: Path):
    music = tmp_path / "m.wav"
    voice = tmp_path / "v.wav"
    _quiet_loud_wav(music, volume=0.2, dur=1.0)
    _quiet_loud_wav(voice, volume=0.3, dur=1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    t1 = ed.add_track("audio")
    t2 = ed.add_track("audio")
    ed.place_from_file(music, "audio", t1.id, 0)
    ed.place_from_file(voice, "audio", t2.id, 0)
    rev = ed.review_cut(expect_music_duck=True, check_brightness_jumps=False)
    codes = [i["code"] for i in rev["issues"]]
    assert "no_ducking" in codes


def test_workflow_includes_delivery_steps(tmp_path: Path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    brief = make_brief(
        intent="vlog",
        assets=[{"path": str(p), "role": "a_roll"}],
        deliverable={"bundle_path": "a.opm", "export_path": "a.mp4"},
    )
    tools = [s["tool"] for s in plan_session(brief)["steps"]]
    assert "review_cut" in tools
    assert "make_sequence_contact_sheet" in tools
    assert "delivery_check" in tools
    assert tools.index("review_cut") < tools.index("export")
    assert tools.index("make_sequence_contact_sheet") < tools.index("export")


def test_editor_export_normalize_preset(tmp_path: Path):
    v = tmp_path / "src.mp4"
    _color_clip(v, dur=0.8)
    ed = Editor.create(tmp_path / "e.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    raw = tmp_path / "out.mp4"
    written = ed.export(raw, normalize_preset="streaming")
    assert written.exists()
    assert written.name.endswith("_loud.mp4")
    check = ed.delivery_check(written, preset="streaming", lufs_tolerance=3.0)
    assert check["probe"]["has_audio"] is True
