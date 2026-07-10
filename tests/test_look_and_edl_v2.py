"""Project look / color_match + plan_edit v2 overlay B-roll."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.asset_analysis import plan_edit
from opmiere.render.look import LOOK_PRESETS, measure_frame_stats, resolve_look
from opmiere.workflow import make_brief, plan_session

FPS = 30


def _clip(path: Path, color: str, dur: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _clip_av(path: Path, color: str, dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_look_presets_resolve():
    assert "cinematic" in LOOK_PRESETS
    fx = resolve_look("cinematic")
    assert any(e["type"] == "curves" for e in fx)
    assert resolve_look("neutral") == []


def test_apply_project_look_and_color_match(tmp_path: Path):
    a = tmp_path / "warm.mp4"
    b = tmp_path / "cool.mp4"
    _clip(a, "orange", 0.6)
    _clip(b, "blue", 0.6)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ca = ed.place_from_file(a, "video", tr.id, 0)
    cb = ed.place_from_file(b, "video", tr.id, ca.end)

    look = ed.apply_project_look("documentary")
    assert look["clip_count"] == 2
    assert look["applied_count"] > 0

    matched = ed.color_match_to_clip(ca.id, [cb.id], strength=0.5)
    assert matched["matched_count"] == 1
    assert matched["matched"][0]["effects"]

    # export still works after grade
    out = tmp_path / "graded.mp4"
    ed.export(out)
    assert out.exists() and out.stat().st_size > 0


def test_plan_edit_overlay_b_roll(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _clip_av(a, "green", 1.2)
    _clip(b, "red", 0.8)
    # Force roles via cards
    from opmiere.render.asset_analysis import analyze_asset
    card_a = analyze_asset(a, do_scenes=False, do_silence=False, do_motion=False)
    card_a["role_guess"] = "a_roll"
    card_b = analyze_asset(b, do_scenes=False, do_silence=False, do_motion=False)
    card_b["role_guess"] = "b_roll"

    plan = plan_edit(
        cards=[card_a, card_b],
        fps=FPS,
        width=160,
        height=90,
        cut_silence=False,
        prefer_scenes=False,
        b_roll_mode="overlay",
        l_cut_seconds=0.2,
        transition_default="hard_cut",
        transition_frames=0,
    )
    assert plan["b_roll_mode"] == "overlay"
    overlays = [e for e in plan["events"] if e.get("track_hint") == "video_overlay"]
    base = [e for e in plan["events"] if e.get("track_hint") == "video_base"]
    assert base
    assert overlays
    assert "timeline_start_frames" in overlays[0]

    ed = Editor.create(tmp_path / "cut.opm", fps=FPS, width=160, height=90)
    result = ed.apply_edit_plan(plan)
    assert result["placed_count"] >= 2
    video_tracks = [t for t in ed.project.tracks if t.kind == "video"]
    assert len(video_tracks) >= 2  # base + overlay
    # overlay clip not forced contiguous from 0
    ov = video_tracks[1]
    assert ov.clips
    ed.export(tmp_path / "overlay_cut.mp4")


def test_workflow_has_look_steps(tmp_path: Path):
    p = tmp_path / "x.mp4"
    p.write_bytes(b"x")
    brief = make_brief(
        intent=None,
        assets=[{"path": str(p), "role": "a_roll"}],
        deliverable={"bundle_path": "a.opm", "export_path": "a.mp4"},
    )
    tools = [s["tool"] for s in plan_session(brief)["steps"]]
    assert "apply_project_look" in tools
    assert "color_match_to_clip" in tools
    assert tools.index("apply_project_look") < tools.index("export")


def test_measure_frame_stats(tmp_path: Path):
    v = tmp_path / "m.mp4"
    _clip(v, "white", 0.4)
    s = measure_frame_stats(v, 0.1)
    assert s["yavg"] is not None
    assert s["yavg"] > 100  # white-ish
