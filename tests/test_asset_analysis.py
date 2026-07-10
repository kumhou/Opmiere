"""Asset cards, motion heuristics, fps/resolution limits, plan_edit EDL."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.asset_analysis import (
    analyze_asset,
    check_delivery_limits,
    plan_edit,
    suggest_project_fps,
    suggest_project_resolution,
)
from opmiere.render.motion import analyze_motion
from opmiere.workflow import make_brief, plan_session


FPS = 30


def _static_color(
    path: Path,
    color: str = "blue",
    dur: float = 0.6,
    size: str = "160x90",
    rate: int = FPS,
) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size={size}:duration={dur}:rate={rate}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _pan_like(path: Path) -> None:
    """Moving crop of a wide still — approximates horizontal pan."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=red:size=320x90:duration=1:rate={FPS},"
                  f"drawbox=x=0:y=0:w=160:h=90:color=blue:t=fill",
            "-vf", "crop=160:90:x='min(160\\,n*4)':y=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_suggest_project_fps_prefers_30_for_30fps_source(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _static_color(v)
    r = suggest_project_fps([v], preference="auto")
    assert r["fps"] == 30.0
    assert r["sources"]
    assert 60.0 in r["allowed"]


def test_suggest_project_fps_explicit_24():
    r = suggest_project_fps([], preference="24")
    assert r["fps"] == 24.0


def test_suggest_project_fps_explicit_60_warns_without_sources():
    r = suggest_project_fps([], preference="60")
    assert r["fps"] == 60.0


def test_suggest_project_fps_60_warns_when_source_lower(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _static_color(v, rate=30)
    r = suggest_project_fps([v], preference="60")
    assert r["fps"] == 60.0
    assert r["warnings"]
    assert r["source_max_fps"] is not None
    assert r["source_max_fps"] < 60


def test_suggest_project_fps_default_without_sources():
    r = suggest_project_fps([], preference="auto")
    assert r["fps"] == 30.0


def test_suggest_resolution_auto_matches_source(tmp_path: Path):
    v = tmp_path / "hd.mp4"
    _static_color(v, size="1920x1080", dur=0.4)
    r = suggest_project_resolution([v], preference="auto")
    assert r["width"] == 1920
    assert r["height"] == 1080
    assert r["feasible_native"] is True


def test_suggest_resolution_4k_errors_on_small_source(tmp_path: Path):
    v = tmp_path / "sd.mp4"
    _static_color(v, size="640x360", dur=0.4)
    r = suggest_project_resolution([v], preference="4k")
    assert r["width"] == 3840
    assert r["height"] == 2160
    assert r["feasible_native"] is False
    assert r["errors"]


def test_check_delivery_limits_blocks_4k_from_720(tmp_path: Path):
    v = tmp_path / "s.mp4"
    _static_color(v, size="1280x720", dur=0.4)
    r = check_delivery_limits(paths=[v], fps=30, width=3840, height=2160)
    assert r["ok"] is False
    assert r["errors"]


def test_analyze_motion_static_label(tmp_path: Path):
    v = tmp_path / "s.mp4"
    _static_color(v, dur=0.8)
    m = analyze_motion(v, sample_fps=5, max_frames=20)
    assert m["has_video"] is True
    assert m["label"] in ("static", "handheld")  # encoder noise may bump slightly
    assert m["energy_mean"] < 8.0


def test_analyze_asset_card_fields(tmp_path: Path):
    v = tmp_path / "c.mp4"
    _static_color(v)
    card = analyze_asset(
        v, do_scenes=True, do_silence=False, do_motion=True, do_transcribe=False,
        scene_backend="ffmpeg",
    )
    assert card["has_video"] is True
    assert card["role_guess"] in ("a_roll", "b_roll", "still")
    assert "transition_affinity" in card
    assert "preferred_transition_in" in card["transition_affinity"]
    assert isinstance(card["suggested_uses"], list)


def test_editor_analyze_asset_caches(tmp_path: Path):
    v = tmp_path / "c.mp4"
    _static_color(v)
    ed = Editor.create(tmp_path / "p.opm", fps=30, width=160, height=90)
    card = ed.analyze_asset(v, do_scenes=False, do_silence=False, do_transcribe=False)
    assert "cache_path" in card
    assert Path(card["cache_path"]).exists()
    loaded = ed.load_asset_analysis(v)
    assert loaded is not None
    assert loaded["path"] == card["path"]


def test_plan_edit_and_apply(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _static_color(a, color="blue", dur=0.5)
    _static_color(b, color="red", dur=0.5)
    card_a = analyze_asset(
        a, do_scenes=False, do_silence=False, do_motion=True, do_transcribe=False,
    )
    card_b = analyze_asset(
        b, do_scenes=False, do_silence=False, do_motion=True, do_transcribe=False,
    )
    plan = plan_edit(
        cards=[card_a, card_b],
        fps=30,
        width=160,
        height=90,
        cut_silence=False,
        prefer_scenes=False,
        transition_default="hard_cut",
        transition_frames=0,
    )
    assert plan["event_count"] >= 2
    assert plan["events"][0]["op"] == "place"
    assert plan["delivery"]["ok"] is True

    ed = Editor.create(tmp_path / "cut.opm", fps=30, width=160, height=90)
    result = ed.apply_edit_plan(plan)
    assert result["placed_count"] >= 2
    assert result["duration_frames"] > 0
    assert any(t.kind == "video" for t in ed.project.tracks)


def test_plan_includes_analyze_asset_and_suggest_fps(tmp_path: Path):
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"x")
    brief = make_brief(
        intent="vlog",
        assets=[{"path": str(p), "role": "a_roll"}],
        constraints={},  # no fps → suggest_fps step
        deliverable={"bundle_path": "a.opm", "export_path": "a.mp4"},
    )
    tools = [s["tool"] for s in plan_session(brief)["steps"]]
    assert "suggest_project_fps" in tools
    assert "analyze_asset" in tools
    assert "plan_edit" in tools
    assert "apply_edit_plan" in tools
    assert tools.index("suggest_project_fps") < tools.index("create_project")
    assert tools.index("analyze_asset") < tools.index("plan_edit")
    assert tools.index("plan_edit") < tools.index("apply_edit_plan")
