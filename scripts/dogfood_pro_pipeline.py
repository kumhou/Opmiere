#!/usr/bin/env python3
"""Phase-A professional pipeline dogfood + machine checklist.

No ComfyUI. Uses test_materials when present (trimmed); else lavfi.
Writes scripts/_dogfood_pro_out/{report.json,checklist.md,export*}.

Exit 0 only if all hard gates pass (doctor, place, export, delivery geometry).

  python scripts/dogfood_pro_pipeline.py
  python scripts/dogfood_pro_pipeline.py --seconds 3
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opmiere import Editor, __version__  # noqa: E402
from opmiere.doctor import run_doctor  # noqa: E402
from opmiere.render.asset_analysis import analyze_asset  # noqa: E402
from opmiere.render.probe import probe  # noqa: E402

OUT = ROOT / "scripts" / "_dogfood_pro_out"
MATERIALS = ROOT / "test_materials"
FPS = 30
W, H = 640, 360


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _lavfi_clip(path: Path, color: str, dur: float = 1.2) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c={color}:size={W}x{H}:duration={dur}:rate={FPS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur},volume=0.15",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path),
    ])


def _trim(src: Path, dest: Path, seconds: float) -> None:
    r = _run(
        ["ffmpeg", "-y", "-i", str(src), "-t", str(seconds), "-c", "copy", str(dest)],
        check=False,
    )
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 500:
        _run([
            "ffmpeg", "-y", "-i", str(src), "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "2", str(dest),
        ])


def prepare_sources(work: Path, seconds: float) -> dict[str, list[Path]]:
    work.mkdir(parents=True, exist_ok=True)
    videos: list[Path] = []
    vids = sorted(MATERIALS.glob("VID_*.mp4")) if MATERIALS.is_dir() else []
    if len(vids) >= 2:
        for i, src in enumerate(vids[:2]):
            dest = work / f"src_{i}.mp4"
            _trim(src, dest, seconds)
            videos.append(dest)
        source_mode = "test_materials"
    else:
        for i, color in enumerate(("0x224466", "0x884422")):
            p = work / f"src_{i}.mp4"
            _lavfi_clip(p, color, min(seconds, 1.5))
            videos.append(p)
        source_mode = "lavfi"
    vo = work / "vo.wav"
    # odd sample rate on purpose — import should resample when conform=True
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={max(seconds, 1.5)},volume=0.08",
        "-ar", "44100", str(vo),
    ])
    music = work / "music.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=110:duration={max(seconds * 2, 2.0)},tremolo=f=2:d=0.7,volume=0.25",
        "-ar", "48000", str(music),
    ])
    return {
        "videos": videos,
        "vo": [vo],
        "music": [music],
        "mode": source_mode,  # type: ignore[dict-item]
    }


def _gate(name: str, ok: bool, detail: str = "") -> dict:
    return {"id": name, "ok": bool(ok), "detail": detail}


def main() -> int:
    ap = argparse.ArgumentParser(description="Opmiere pro pipeline dogfood")
    ap.add_argument("--seconds", type=float, default=2.5, help="trim length for real clips")
    args = ap.parse_args()

    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    gates: list[dict] = []
    report: dict = {
        "opmiere_version": __version__,
        "steps": [],
        "gates": gates,
    }

    doc = run_doctor(check_comfy=False)
    gates.append(_gate("doctor", doc["ok"], doc.get("summary", "")))
    report["doctor"] = {"ok": doc["ok"], "errors": doc.get("errors")}
    report["steps"].append({"step": "doctor", "ok": doc["ok"]})
    if not doc["ok"]:
        _write_reports(report, t0)
        print("FAIL doctor")
        return 1

    src = prepare_sources(OUT / "src", args.seconds)
    report["source_mode"] = src["mode"]
    videos: list[Path] = src["videos"]  # type: ignore[assignment]
    vo_path: Path = src["vo"][0]  # type: ignore[index]
    music_path: Path = src["music"][0]  # type: ignore[index]

    cards = []
    for i, p in enumerate(videos):
        c = analyze_asset(
            p, do_scenes=True, do_silence=False, do_motion=True,
            do_transcribe=False, scene_backend="ffmpeg",
        )
        c["role_guess"] = "a_roll" if i == 0 else "b_roll"
        cards.append(c)
    vo_card = analyze_asset(
        vo_path, do_scenes=False, do_silence=False, do_motion=False, do_transcribe=False,
    )
    vo_card["role_guess"] = "vo"
    cards.append(vo_card)
    mu_card = analyze_asset(
        music_path, do_scenes=False, do_silence=False, do_motion=False, do_transcribe=False,
    )
    mu_card["role_guess"] = "music"
    cards.append(mu_card)
    report["steps"].append({"step": "analyze_asset", "cards": len(cards)})
    gates.append(_gate("analyze", len(cards) >= 3, f"{len(cards)} cards"))

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
        j_cut_seconds=0.3,
        black_pad_j_cut=True,
        use_music_beats=True,
        transition_default="cross_dissolve",
        transition_frames=4,
        l_cut_seconds=0.12,
    )
    applied = ed.apply_edit_plan(plan)
    report["plan"] = {
        "event_count": plan["event_count"],
        "placed": applied["placed_count"],
        "errors": applied.get("errors"),
        "warnings": plan.get("warnings"),
    }
    gates.append(_gate(
        "apply_edit_plan",
        applied["placed_count"] >= 2 and not applied.get("errors"),
        f"placed={applied['placed_count']} errors={applied.get('errors')}",
    ))

    # audio resample check: VO was 44100
    vo_media = [m for m in ed.project.media if m.origin and m.origin.get("conformed")]
    gates.append(_gate(
        "audio_or_video_conform_used",
        len(vo_media) >= 1 or any(
            (m.origin or {}).get("conformed") for m in ed.project.media
        ),
        f"conformed_media={sum(1 for m in ed.project.media if (m.origin or {}).get('conformed'))}",
    ))

    look = ed.apply_project_look("documentary")
    report["steps"].append({"step": "look", "clips": look.get("clip_count")})
    gates.append(_gate("project_look", look.get("clip_count", 0) > 0))

    from opmiere.render.mix_suggest import suggest_mix
    mix = suggest_mix(vo_path=vo_path, music_path=music_path)
    # resolve track ids
    audio_tracks = [t for t in ed.project.tracks if t.kind == "audio"]
    if len(audio_tracks) >= 2:
        mix_app = ed.apply_mix_plan(
            mix,
            music_track_id=audio_tracks[0].id,
            vo_track_id=audio_tracks[1].id if len(audio_tracks) > 1 else audio_tracks[0].id,
        )
        report["mix"] = {"applied": mix_app.get("applied_count"), "errors": mix_app.get("errors")}
        gates.append(_gate("mix_plan", mix_app.get("applied_count", 0) >= 1))
    else:
        gates.append(_gate("mix_plan", False, "need 2 audio tracks"))

    rev = ed.review_cut(check_brightness_jumps=True, expect_music_duck=True)
    report["review_cut"] = {"ok": rev["ok"], "issues": rev.get("issues")}
    # review ok = no severity error
    gates.append(_gate("review_cut_no_errors", rev["ok"], f"issues={rev.get('error_count')}"))

    try:
        sheet = ed.make_sequence_contact_sheet(OUT / "sequence_sheet.png", max_tiles=8)
        gates.append(_gate("sequence_sheet", Path(sheet["path"]).exists()))
    except Exception as e:
        gates.append(_gate("sequence_sheet", False, str(e)))

    # preview
    try:
        px = ed.export_preview(OUT / "preview_proxy.mp4", height=180, fps=8)
        fr = ed.frame_at(0.2, OUT / "frame.jpg", prefer_proxy=True)
        gates.append(_gate(
            "preview",
            Path(px["path"]).exists() and Path(fr["path"]).exists(),
            f"mode={fr.get('mode')}",
        ))
        st = ed.preview_proxy_status()
        gates.append(_gate("preview_fresh", st.get("fresh") is True))
    except Exception as e:
        gates.append(_gate("preview", False, str(e)))
        gates.append(_gate("preview_fresh", False, str(e)))

    written = ed.export(OUT / "export.mp4", normalize_preset="streaming")
    dc = ed.delivery_check(written, preset="streaming", lufs_tolerance=3.5)
    report["export"] = {
        "path": str(written),
        "size": written.stat().st_size if written.exists() else 0,
        "delivery": {
            "ok": dc.get("ok"),
            "errors": dc.get("errors"),
            "warnings": dc.get("warnings"),
        },
    }
    gates.append(_gate("export_exists", written.exists() and written.stat().st_size > 1000))
    # Geometry must match; loudness may warn on short synthetic
    geo_ok = not any(
        "width" in e or "height" in e or "fps" in e
        for e in (dc.get("errors") or [])
    )
    gates.append(_gate("delivery_geometry", geo_ok, str(dc.get("errors"))))
    info = probe(written)
    gates.append(_gate(
        "export_probe",
        bool(info.has_video and info.duration_seconds > 0.2),
        f"dur={info.duration_seconds:.2f} {info.width}x{info.height}",
    ))

    ed.save()
    hard = [g for g in gates if g["id"] in {
        "doctor", "analyze", "apply_edit_plan", "project_look",
        "export_exists", "delivery_geometry", "export_probe",
    }]
    report["ok"] = all(g["ok"] for g in hard)
    report["gates_passed"] = sum(1 for g in gates if g["ok"])
    report["gates_total"] = len(gates)
    report["elapsed_seconds"] = round(time.time() - t0, 2)
    _write_reports(report, t0)

    summary = {
        "ok": report["ok"],
        "version": __version__,
        "gates": f"{report['gates_passed']}/{report['gates_total']}",
        "export": str(written),
        "delivery_ok": dc.get("ok"),
        "elapsed_s": report["elapsed_seconds"],
        "report": str(OUT / "report.json"),
        "checklist": str(OUT / "checklist.md"),
    }
    print(json.dumps(summary, indent=2))
    return 0 if report["ok"] else 1


def _write_reports(report: dict, t0: float) -> None:
    report.setdefault("elapsed_seconds", round(time.time() - t0, 2))
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    lines = [
        f"# Dogfood checklist — Opmiere {report.get('opmiere_version')}",
        "",
        f"ok={report.get('ok')}  gates={report.get('gates_passed')}/{report.get('gates_total')}  "
        f"elapsed={report.get('elapsed_seconds')}s  source={report.get('source_mode')}",
        "",
        "| Gate | OK | Detail |",
        "|------|----|--------|",
    ]
    for g in report.get("gates") or []:
        mark = "PASS" if g.get("ok") else "FAIL"
        detail = str(g.get("detail") or "").replace("|", "/")[:80]
        lines.append(f"| `{g.get('id')}` | {mark} | {detail} |")
    lines += [
        "",
        "## Manual eyes (human)",
        "- [ ] Sequence sheet pacing looks intentional",
        "- [ ] No black/frozen stretch in export",
        "- [ ] VO audible over music (if both present)",
        "- [ ] Delivery claim honest (no fake 4k/60)",
        "",
    ]
    (OUT / "checklist.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
