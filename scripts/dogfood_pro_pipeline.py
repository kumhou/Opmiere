#!/usr/bin/env python3
"""End-to-end professional pipeline dogfood (no ComfyUI required).

Uses test_materials when present; otherwise short lavfi clips.
Writes report + export under scripts/_dogfood_pro_out/.

  python scripts/dogfood_pro_pipeline.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opmiere import Editor  # noqa: E402
from opmiere.doctor import run_doctor  # noqa: E402
from opmiere.render.asset_analysis import analyze_asset  # noqa: E402

OUT = ROOT / "scripts" / "_dogfood_pro_out"
MATERIALS = ROOT / "test_materials"
FPS = 30
W, H = 640, 360


def _lavfi_clip(path: Path, color: str, dur: float = 1.2) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size={W}x{H}:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur},volume=0.15",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def _trim_copy(src: Path, dest: Path, seconds: float = 2.5) -> None:
    """Shorten only — import_media auto-conforms fps to project timebase."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src), "-t", str(seconds),
            "-c", "copy", str(dest),
        ],
        capture_output=True, text=True, check=True,
    )
    # If stream-copy fails (odd codecs), re-encode without fps force
    if not dest.exists() or dest.stat().st_size < 1000:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(src), "-t", str(seconds),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ac", "2", str(dest),
            ],
            capture_output=True, text=True, check=True,
        )


def prepare_sources(work: Path) -> list[Path]:
    work.mkdir(parents=True, exist_ok=True)
    vids = sorted(MATERIALS.glob("VID_*.mp4")) if MATERIALS.is_dir() else []
    paths: list[Path] = []
    if len(vids) >= 2:
        for i, src in enumerate(vids[:2]):
            dest = work / f"src_{i}.mp4"
            _trim_copy(src, dest, 2.0)
            paths.append(dest)
    else:
        for i, color in enumerate(("0x224466", "0x884422")):
            p = work / f"src_{i}.mp4"
            _lavfi_clip(p, color, 1.2)
            paths.append(p)
    # quiet VO bed
    vo = work / "vo.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=220:duration=2.5,volume=0.08",
            "-ar", "48000", str(vo),
        ],
        capture_output=True, text=True, check=True,
    )
    paths.append(vo)
    return paths


def main() -> int:
    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"steps": []}

    doc = run_doctor(check_comfy=False)
    report["doctor"] = {"ok": doc["ok"], "errors": doc.get("errors"), "summary": doc.get("summary")}
    report["steps"].append({"step": "doctor", "ok": doc["ok"]})
    if not doc["ok"]:
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("doctor failed — abort")
        return 1

    sources = prepare_sources(OUT / "src")
    video_paths = [p for p in sources if p.suffix.lower() == ".mp4"]
    vo_path = next(p for p in sources if p.suffix.lower() == ".wav")

    cards = []
    for p in video_paths:
        c = analyze_asset(p, do_scenes=True, do_silence=False, do_motion=True, do_transcribe=False, scene_backend="ffmpeg")
        c["role_guess"] = "a_roll" if not cards else "b_roll"
        cards.append(c)
    vo_card = analyze_asset(vo_path, do_scenes=False, do_silence=False, do_motion=False, do_transcribe=False)
    vo_card["role_guess"] = "vo"
    cards.append(vo_card)
    report["steps"].append({"step": "analyze_asset", "cards": len(cards)})

    bundle = OUT / "cut.opm"
    ed = Editor.create(bundle, fps=FPS, width=W, height=H)
    plan = ed.plan_edit(
        cards=cards,
        fps=FPS,
        width=W,
        height=H,
        cut_silence=False,
        prefer_scenes=False,
        b_roll_mode="overlay",
        j_cut_seconds=0.35,
        black_pad_j_cut=True,
        use_music_beats=False,
        transition_default="cross_dissolve",
        transition_frames=6,
        l_cut_seconds=0.15,
    )
    report["plan"] = {
        "event_count": plan["event_count"],
        "j_pad_frames": plan.get("j_pad_frames"),
        "warnings": plan.get("warnings"),
    }
    applied = ed.apply_edit_plan(plan)
    report["steps"].append({
        "step": "apply_edit_plan",
        "placed": applied["placed_count"],
        "errors": applied.get("errors"),
    })

    look = ed.apply_project_look("documentary")
    report["steps"].append({"step": "apply_project_look", "clips": look.get("clip_count")})

    # mix: VO track vs nothing else — still exercise suggest
    from opmiere.render.mix_suggest import suggest_mix
    mix = suggest_mix(vo_path=vo_path)
    report["mix"] = {"actions": mix.get("actions")}

    rev = ed.review_cut(check_brightness_jumps=True, expect_music_duck=False)
    report["review_cut"] = {
        "ok": rev["ok"],
        "issues": rev.get("issues"),
        "duration_seconds": rev.get("duration_seconds"),
    }
    report["steps"].append({"step": "review_cut", "ok": rev["ok"]})

    sheet_path = OUT / "sequence_sheet.png"
    try:
        sheet = ed.make_sequence_contact_sheet(sheet_path, max_tiles=8, cols=4)
        report["sequence_sheet"] = sheet.get("path")
        report["steps"].append({"step": "sequence_sheet", "ok": True})
    except Exception as e:
        report["steps"].append({"step": "sequence_sheet", "ok": False, "error": str(e)})

    export_raw = OUT / "export.mp4"
    written = ed.export(export_raw, normalize_preset="streaming")
    dc = ed.delivery_check(written, preset="streaming", lufs_tolerance=3.0)
    report["export"] = {
        "path": str(written),
        "size": written.stat().st_size if written.exists() else 0,
        "delivery_ok": dc.get("ok"),
        "delivery_errors": dc.get("errors"),
        "delivery_warnings": dc.get("warnings"),
    }
    report["steps"].append({"step": "export+delivery", "ok": written.exists()})

    ed.save()
    report["elapsed_seconds"] = round(time.time() - t0, 2)
    report["ok"] = bool(
        doc["ok"] and applied["placed_count"] >= 1 and written.exists()
    )
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(json.dumps({
        "ok": report["ok"],
        "export": str(written),
        "delivery_ok": dc.get("ok"),
        "placed": applied["placed_count"],
        "review_ok": rev["ok"],
        "elapsed_s": report["elapsed_seconds"],
        "report": str(OUT / "report.json"),
    }, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

