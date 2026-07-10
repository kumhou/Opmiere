#!/usr/bin/env python3
"""Dogfood: cut template → finish_delivery (export + delivery_check).

Uses test_materials when present; else lavfi. No ComfyUI.

  python scripts/dogfood_template_pipeline.py
  python scripts/dogfood_template_pipeline.py --template short_form --seconds 1.5

Exit 0 if hard gates pass (doctor, template place, export geometry).
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
from opmiere.render.probe import probe  # noqa: E402

OUT = ROOT / "scripts" / "_dogfood_template_out"
MATERIALS = ROOT / "test_materials"
FPS = 30
W, H = 640, 360


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _lavfi(path: Path, color: str, dur: float) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c={color}:size={W}x{H}:duration={dur}:rate={FPS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur},volume=0.12",
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
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dest),
        ])


def prepare(work: Path, seconds: float) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    videos: list[Path] = []
    vids = sorted(MATERIALS.glob("VID_*.mp4")) if MATERIALS.is_dir() else []
    mode = "lavfi"
    if len(vids) >= 2:
        mode = "test_materials"
        for i, src in enumerate(vids[:2]):
            dest = work / f"v{i}.mp4"
            _trim(src, dest, seconds)
            videos.append(dest)
    else:
        for i, c in enumerate(("0x1a3a5a", "0x5a3a1a")):
            p = work / f"v{i}.mp4"
            _lavfi(p, c, min(seconds, 1.2))
            videos.append(p)
    music = work / "music.wav"
    vo = work / "vo.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=100:duration={max(seconds * 2, 2)},volume=0.2",
        "-ar", "48000", str(music),
    ])
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=300:duration={max(seconds, 1.2)},volume=0.1",
        "-ar", "48000", str(vo),
    ])
    return {"videos": videos, "music": music, "vo": vo, "mode": mode}


def _gate(name: str, ok: bool, detail: str = "") -> dict:
    return {"id": name, "ok": bool(ok), "detail": detail}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="talking_head")
    ap.add_argument("--seconds", type=float, default=2.0)
    args = ap.parse_args()

    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    gates: list[dict] = []
    report: dict = {
        "opmiere_version": __version__,
        "template": args.template,
        "gates": gates,
    }

    doc = run_doctor(check_comfy=False)
    gates.append(_gate("doctor", doc["ok"], doc.get("summary", "")))
    if not doc["ok"]:
        _write(report, t0)
        return 1

    src = prepare(OUT / "src", args.seconds)
    report["source_mode"] = src["mode"]
    paths = [str(p) for p in src["videos"]] + [str(src["music"]), str(src["vo"])]

    bundle = OUT / "tpl.opm"
    ed = Editor.create(bundle, fps=FPS, width=W, height=H)
    dry = ed.apply_cut_template(args.template, paths=paths, dry_run=True)
    gates.append(_gate("template_dry", dry.get("applied") is False, dry.get("label", "")))

    applied = ed.apply_cut_template(
        args.template, paths=paths, dry_run=False, apply_silence=False,
    )
    report["template_result"] = {
        "applied": applied.get("applied"),
        "style": applied.get("style"),
        "batch": (applied.get("batch") or {}).get("placed_count"),
        "duck": applied.get("duck"),
        "hints": len(applied.get("hints") or []),
    }
    placed = (applied.get("batch") or {}).get("placed_count") or 0
    gates.append(_gate("template_apply", bool(applied.get("applied")) and placed >= 1,
                       f"placed={placed} style={applied.get('style')}"))

    # layout edit smoke: edge trim first clip then pack base track (export needs contiguity)
    vtracks = [t for t in ed.project.tracks if t.kind == "video"]
    vclips = [c for t in vtracks for c in t.clips]
    if vclips:
        try:
            ed.edge_trim(vclips[0].id, "right", -3, mode="normal")
            ed.close_gaps(vtracks[0].id, from_frame=0)
            gates.append(_gate("edge_trim", True))
        except Exception as e:
            gates.append(_gate("edge_trim", False, str(e)[:120]))

    # mix view
    mix = ed.mix_view()
    gates.append(_gate("mix_view", mix.get("audio_track_count", 0) >= 1,
                       f"audio={mix.get('audio_track_count')} duck={len(mix.get('duck_edges') or [])}"))

    # quick proxy
    try:
        px = ed.refresh_preview_proxy(quick=True, force=True)
        gates.append(_gate("quick_proxy", Path(px.get("path") or "").exists()))
    except Exception as e:
        gates.append(_gate("quick_proxy", False, str(e)[:120]))

    fin = ed.finish_delivery(
        OUT / "export.mp4",
        normalize_preset="streaming",
        run_review=True,
        run_sequence_sheet=True,
        sequence_sheet_path=OUT / "sheet.png",
    )
    report["finish"] = {
        "ok": fin.get("ok"),
        "delivery_ok": fin.get("delivery_ok"),
        "export": fin.get("export"),
        "review_ok": (fin.get("review") or {}).get("ok"),
    }
    gates.append(_gate("finish_ok", bool(fin.get("ok")), str(fin.get("export"))))
    exp = Path((fin.get("export") or {}).get("path") or "")
    if exp.exists():
        info = probe(exp)
        gates.append(_gate(
            "export_probe",
            bool(info.has_video and info.duration_seconds > 0.15),
            f"dur={info.duration_seconds:.2f}",
        ))
    else:
        gates.append(_gate("export_probe", False, "missing"))

    # list templates / style assets inventory (no crash)
    gates.append(_gate("list_templates", "talking_head" in ed.list_cut_templates()["names"]))
    gates.append(_gate("list_style_assets", "search_dirs" in ed.list_style_assets()))

    ed.save()
    hard_ids = {"doctor", "template_apply", "finish_ok", "export_probe"}
    hard = [g for g in gates if g["id"] in hard_ids]
    report["ok"] = all(g["ok"] for g in hard)
    report["gates_passed"] = sum(1 for g in gates if g["ok"])
    report["gates_total"] = len(gates)
    report["elapsed_seconds"] = round(time.time() - t0, 2)
    _write(report, t0)

    print(json.dumps({
        "ok": report["ok"],
        "version": __version__,
        "template": args.template,
        "gates": f"{report['gates_passed']}/{report['gates_total']}",
        "source": src["mode"],
        "export": str(exp) if exp else None,
        "report": str(OUT / "report.json"),
    }, indent=2))
    return 0 if report["ok"] else 1


def _write(report: dict, t0: float) -> None:
    report.setdefault("elapsed_seconds", round(time.time() - t0, 2))
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    lines = [
        f"# Template dogfood — Opmiere {report.get('opmiere_version')}",
        "",
        f"template={report.get('template')} ok={report.get('ok')} "
        f"gates={report.get('gates_passed')}/{report.get('gates_total')}",
        "",
        "| Gate | OK | Detail |",
        "|------|----|--------|",
    ]
    for g in report.get("gates") or []:
        mark = "PASS" if g.get("ok") else "FAIL"
        detail = str(g.get("detail") or "").replace("|", "/")[:100]
        lines.append(f"| `{g.get('id')}` | {mark} | {detail} |")
    (OUT / "checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
