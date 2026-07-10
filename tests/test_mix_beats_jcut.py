"""suggest_mix, detect_beats, J-cut black pad."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor
from opmiere.render.asset_analysis import analyze_asset, plan_edit
from opmiere.render.beats import detect_beats, phrase_anchors
from opmiere.render.mix_suggest import suggest_dialogue_chain, suggest_mix
from opmiere.workflow import make_brief, plan_session

FPS = 30


def _tone(path: Path, freq: float, dur: float, volume: float = 0.2) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={dur},volume={volume}",
            "-ar", "48000", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _pulse_music(path: Path, dur: float = 4.0) -> None:
    """Amplitude-modulated tone → detectable energy peaks."""
    # 2 Hz amplitude envelope-ish via tremolo
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=220:duration={dur},tremolo=f=2:d=0.9",
            "-ar", "22050", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _video(path: Path, color: str = "blue", dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_detect_beats_finds_onsets(tmp_path: Path):
    m = tmp_path / "m.wav"
    _pulse_music(m, dur=3.0)
    r = detect_beats(m, max_seconds=3.0, sensitivity=1.05)
    assert r["beat_count"] >= 2
    assert r["beat_times"][0] >= 0
    phrases = phrase_anchors(r["beat_times"], every_n=2)
    assert phrases


def test_suggest_mix_recommends_gain_and_duck(tmp_path: Path):
    vo = tmp_path / "vo.wav"
    music = tmp_path / "music.wav"
    _tone(vo, 880, 1.5, volume=0.05)   # quiet VO → positive gain
    _tone(music, 220, 2.0, volume=0.4)  # loud music → negative gain
    plan = suggest_mix(vo_path=vo, music_path=music)
    ops = {a["op"] for a in plan["actions"]}
    assert "set_ducking" in ops
    gains = [a for a in plan["actions"] if a["op"] == "gain"]
    assert gains
    chain = suggest_dialogue_chain(vo)
    assert chain["steps"]
    assert "suggested_gain_db" in chain


def test_apply_mix_plan(tmp_path: Path):
    vo = tmp_path / "vo.wav"
    music = tmp_path / "music.wav"
    _tone(vo, 880, 1.0, volume=0.08)
    _tone(music, 220, 1.5, volume=0.35)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tm = ed.add_track("audio")
    tv = ed.add_track("audio")
    cm = ed.place_from_file(music, "audio", tm.id, 0)
    cv = ed.place_from_file(vo, "audio", tv.id, 0)
    plan = suggest_mix(
        vo_path=vo, music_path=music,
        vo_track_id=tv.id, music_track_id=tm.id,
    )
    result = ed.apply_mix_plan(
        plan,
        role_clip_ids={"vo": [cv.id], "music": [cm.id]},
        music_track_id=tm.id,
        vo_track_id=tv.id,
    )
    assert result["applied_count"] >= 1
    assert tm.duck is not None
    assert tm.duck["against"] == tv.id


def test_jcut_black_pad_plan_and_apply(tmp_path: Path):
    v = tmp_path / "a.mp4"
    vo = tmp_path / "vo.wav"
    _video(v, "green", 1.0)
    _tone(vo, 440, 1.2, volume=0.15)
    card_v = analyze_asset(v, do_scenes=False, do_silence=False, do_motion=False)
    card_v["role_guess"] = "a_roll"
    card_vo = analyze_asset(vo, do_scenes=False, do_silence=False, do_motion=False)
    card_vo["role_guess"] = "vo"
    plan = plan_edit(
        cards=[card_v, card_vo],
        fps=FPS,
        width=160,
        height=90,
        cut_silence=False,
        prefer_scenes=False,
        j_cut_seconds=0.5,
        black_pad_j_cut=True,
        transition_default="hard_cut",
        transition_frames=0,
        use_music_beats=False,
    )
    blacks = [e for e in plan["events"] if e.get("op") == "place_black"]
    assert blacks
    assert plan["j_pad_frames"] > 0

    ed = Editor.create(tmp_path / "j.opm", fps=FPS, width=160, height=90)
    result = ed.apply_edit_plan(plan)
    assert result["placed_count"] >= 2
    base = next(t for t in ed.project.tracks if t.kind == "video")
    ordered = base.clips_in_order()
    assert ordered[0].start == 0
    # second clip starts after black pad
    assert ordered[1].start >= plan["j_pad_frames"] - 1
    ed.export(tmp_path / "jcut.mp4")


def test_workflow_has_mix_steps(tmp_path: Path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    brief = make_brief(
        intent="vlog",
        assets=[{"path": str(p), "role": "a_roll"}],
        deliverable={"bundle_path": "a.opm", "export_path": "a.mp4"},
    )
    tools = [s["tool"] for s in plan_session(brief)["steps"]]
    assert "suggest_mix" in tools
    assert "apply_mix_plan" in tools
