#!/usr/bin/env python3
"""Dogfood: agent_preflight → template cut → agent_finish_session.

No ComfyUI. Proves the 0.3.x agent default path end-to-end.

  python scripts/dogfood_agent_pipeline.py
  python scripts/dogfood_agent_pipeline.py --seconds 1.2

Exit 0 if preflight ready, finish ok, export exists, proxy built.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opmiere import Editor, __version__  # noqa: E402
from opmiere.doctor import run_doctor  # noqa: E402

OUT = ROOT / "scripts" / "_dogfood_agent_out"
FPS = 30
W, H = 640, 360


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def _lavfi(path: Path, color: str, dur: float) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c={color}:size={W}x{H}:duration={dur}:rate={FPS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur},volume=0.1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path),
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=1.2)
    ap.add_argument("--template", default="talking_head")
    args = ap.parse_args()

    if OUT.exists():
        import shutil
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / "src"
    src.mkdir()
    v0, v1 = src / "v0.mp4", src / "v1.mp4"
    _lavfi(v0, "0x1a3a5a", args.seconds)
    _lavfi(v1, "0x5a3a1a", args.seconds)
    vo = src / "vo.wav"
    music = src / "music.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={args.seconds}",
        "-c:a", "pcm_s16le", str(vo),
    ])
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=110:duration={args.seconds}",
        "-c:a", "pcm_s16le", str(music),
    ])

    doc = run_doctor(check_comfy=False)
    gates: dict = {"doctor_ok": bool(doc.get("ok")), "version": __version__}

    ed = Editor.create(OUT / "agent.opm", fps=FPS, width=W, height=H)
    # place via template (paths auto-split video/audio)
    tpl = ed.apply_cut_template(
        args.template,
        paths=[str(v0), str(v1), str(vo), str(music)],
    )
    gates["template"] = {
        "name": args.template,
        "ok": True,
        "keys": list(tpl.keys())[:12],
    }
    ed.save()

    pre = ed.agent_preflight()
    gates["preflight_ready"] = bool(pre.get("ready"))
    gates["preflight_next"] = pre.get("next_steps")
    gates["proxy_before"] = pre.get("proxy", {}).get("fresh")

    # mutate once → proxy must go stale then finish rebuilds
    if ed.project.tracks and ed.project.tracks[0].clips:
        cid = ed.project.tracks[0].clips[0].id
        ed.set_clip_meta(cid, name="dogfood_agent")
    st = ed.preview_proxy_status()
    gates["proxy_stale_after_edit"] = not bool(st.get("fresh"))

    export_path = OUT / "export.mp4"
    fin = ed.agent_finish_session(
        export_path,
        prepare=True,
        ensure_proxy=True,
        proxy_height=180,
        proxy_fps=8.0,
        run_review=True,
        normalize_preset=None,  # faster CI; geometry gate still runs
    )
    gates["finish_ok"] = bool(fin.get("ok"))
    gates["delivery_ok"] = bool(fin.get("delivery_ok"))
    gates["export_exists"] = export_path.exists() and export_path.stat().st_size > 500
    gates["steps"] = fin.get("steps")

    # reopen: meta should load; fingerprint match if no further edit
    ed2 = Editor.open(OUT / "agent.opm")
    st2 = ed2.preview_proxy_status()
    gates["proxy_reopen_exists"] = bool(st2.get("exists"))
    gates["proxy_reopen_fresh"] = bool(st2.get("fresh"))
    meta_p = ed2.bundle.root / "review" / "preview_proxy.meta.json"
    gates["proxy_meta_exists"] = meta_p.exists()
    gates["proxy_final_fresh"] = bool((fin.get("proxy_final") or {}).get("fresh"))

    hard = [
        gates["doctor_ok"],
        gates["preflight_ready"],
        gates["finish_ok"],
        gates["export_exists"],
        gates["proxy_meta_exists"],
        gates["proxy_reopen_exists"],
        gates["proxy_reopen_fresh"],
        gates["proxy_final_fresh"],
    ]
    gates["hard_ok"] = all(hard)
    report = OUT / "report.json"
    report.write_text(json.dumps(gates, indent=2), encoding="utf-8")
    print(json.dumps(gates, indent=2))
    return 0 if gates["hard_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
