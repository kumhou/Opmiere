"""Film-session workflow — the productized *process* layer over tools.

ARCHITECTURE §5.10 hands and feet are the Editor/MCP tools; the brain is an
external agent. This module is the missing middle: a versioned brief schema +
defaults when the user has no opinion + an ordered step plan that names real
tools. It deliberately does NOT run generation or edit the timeline — that
stays agent-driven so quality_check/contact_sheet staging is not collapsed.

Typical agent cold start:
  get_film_workflow() → make_director_brief(...) → plan_director_session(brief)
  → execute steps with real MCP tools → export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WORKFLOW_VERSION = "1.0"

# When the user gives assets but no creative direction, the agent still needs
# a coherent default — not invent a new aesthetic every session.
DEFAULT_AESTHETIC: dict[str, Any] = {
    "emotional_arc": "understated setup → small turn → calm resolve",
    "pace": "unhurried; prefer fewer stronger shots over montage spam",
    "grade": "subtle; white_balance cool→neutral→warm across the arc if multi-shot",
    "transitions": "cross_dissolve between related shots; hard cut only for contrast",
    "audio": "music bed under VO with set_ducking; SFX sparse and intentional",
    "text": "optional end title only; avoid lower-thirds unless user asked",
    "generation": "prefer user assets; generate only gaps (B-roll, VO, music, SFX)",
}

ASSET_ROLES = frozenset({
    "a_roll", "b_roll", "vo", "vo_ref", "music", "sfx", "still", "other",
})

WORKFLOW_MARKDOWN = """\
# Opmiere film session workflow v{version}

End-to-end process for: user materials + (optional) creative intent → cut.
Tools do the work; this document is the order. Call `get_director_policy` for
per-fragment quality gates; call `plan_director_session` for a step list.

## 0. Intake
1. Collect **assets** (paths) and **intent** (free text). Empty intent = use
   `defaults` from `get_film_workflow` / `make_director_brief` — do not invent
   a conflicting style.
2. `make_director_brief` then `validate_director_brief` (or trust make_* output).
3. `plan_director_session(brief)` → ordered steps. Follow them; skip only with reason.

## 1. Project
1. `suggest_project_fps(paths)` when constraints.fps unset — **24 / 30 / 60**
   (also 25/50) from user A-roll; highest honest option is 60 when sources
   support it (not 16 from a generated draft).
2. `suggest_project_resolution(paths)` when width/height unset — ladder up to
   **4k**, but only if sources have those pixels. Then `check_delivery_limits`
   if the user asked for high fps/res: if ok=false, **warn the user** and
   lower the target — do not claim native 4k/60fps from weaker material.
3. `create_project(bundle_path, fps, width, height)`.
4. `get_project_state` before any id-based call.
5. `analyze_asset` each user file → role_guess, motion, transition_affinity,
   scenes, silence; use cards for `plan_edit` / shot allocation.

## 2. Ingest user assets first
1. Prefer `plan_edit` → review events → `apply_edit_plan` for a first cut from
   cards (silence keep_ranges / scenes / affinity transitions). Or manual
   `place_from_file` / import + place per asset.
2. Prefer **user media over generation** when a role is already filled
   (a_roll, music, vo). Generate only for **gaps**.
3. `quality_check` on questionable user files (silent VO, black video) before
   building structure on top of them.
4. **Understand speech:** `transcribe` (faster-whisper) on talking footage →
   `write_srt` / `caption_clip` to burn captions. `suggest_silence_cuts` for
   dead-air keep_ranges (agent trims; no auto-destruct of the timeline).

## 3. Structure the cut
1. Order A-roll / hero shots on the base video track (`place_after` + optional
   `transition_type`), or refine the auto EDL from `apply_edit_plan`.
2. Overlay B-roll / PiP / keyed layers on later video tracks.
3. Timing: use silence keep_ranges to cut dead air; `set_speed` sparingly; leave room for VO.

## 4. Generate only gaps
1. `recommend_generation_profile(kind)` when unsure of model.
2. Per fragment: `generate` → poll `job_status` → `quality_check` →
   `make_contact_sheet` (video) → decide → `place_generated` / upscale / redo.
3. Continuity: shared prompt anchors + same seed when iterating one shot.

## 5. Grade and polish
1. **Session look:** `list_look_presets` → `apply_project_look("cinematic"|…)`
   so the cut shares one grade language (prefer over per-clip freestyle).
2. **Continuity:** `color_match_to_clip(hero_clip_id)` to pull drifted shots
   toward a hero reference (deterministic; not a re-generate).
3. Extra deterministic polish: `color`, `curves`, `lut3d`, `white_balance`,
   `ken_burns`, `text`, stylize — not re-generate for small look fixes.
4. Audio: `suggest_mix(vo_path, music_path)` → `apply_mix_plan` (gain + ducking).
   Optional `suggest_dialogue_chain` on VO before place. `set_ducking` manually
   if preferred; `gain` for fine trim.
5. `analyze_timeline` to verify the mix (ducking room, peaks).

## 6. Deliver
1. `review_cut` — fix severity=error (gaps, empty base); note craft warnings.
2. `make_sequence_contact_sheet` — judge whole-cut pacing/continuity in one image.
3. `export(export_path, normalize_preset=\"streaming\")` for net delivery loudness
   (or normalize_loudness on the raw export). Prefer -14 LUFS streaming /
   youtube / bilibili; broadcast -23.
4. `delivery_check(export_path)` — **required**. ok=false → fix levels/specs or
   warn the user; do not claim professional delivery.
5. Optional per-file `quality_check` / contact_sheet already embedded in
   delivery_check when video/audio present.
6. Report: brief version, generated vs user media, `get_license_report` if needed.

## Anti-patterns
- Generate B-roll before placing the user's A-roll.
- place_generated before quality_check.
- Ignoring empty intent (must apply DEFAULT_AESTHETIC, not freestyle chaos).
- Skipping plan_director_session and freelancing tool order without reason.
""".format(version=WORKFLOW_VERSION)


def make_brief(
    *,
    intent: str | None = None,
    assets: list[dict[str, Any]] | None = None,
    constraints: dict[str, Any] | None = None,
    deliverable: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a director brief. Empty/None intent → no_opinion + DEFAULT_AESTHETIC."""
    intent_clean = (intent or "").strip()
    no_opinion = intent_clean == ""
    assets_in = list(assets or [])
    constraints_in = dict(constraints or {})
    deliverable_in = dict(deliverable or {})

    brief: dict[str, Any] = {
        "workflow_version": WORKFLOW_VERSION,
        "intent": intent_clean if not no_opinion else None,
        "no_opinion": no_opinion,
        "defaults_applied": dict(DEFAULT_AESTHETIC) if no_opinion else None,
        "assets": assets_in,
        "constraints": {
            "duration_seconds": constraints_in.get("duration_seconds"),
            "language": constraints_in.get("language", "zh"),
            "no_generate": bool(constraints_in.get("no_generate", False)),
            "fps": constraints_in.get("fps"),
            "width": constraints_in.get("width", 1920),
            "height": constraints_in.get("height", 1080),
        },
        "deliverable": {
            "bundle_path": deliverable_in.get("bundle_path"),
            "export_path": deliverable_in.get("export_path"),
        },
    }
    return brief


def validate_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Validate a brief. Returns {ok, errors, warnings} — never raises on soft issues."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(brief, dict):
        return {"ok": False, "errors": ["brief must be a dict"], "warnings": []}

    assets = brief.get("assets")
    if assets is None:
        assets = []
    if not isinstance(assets, list):
        errors.append("assets must be a list")
        assets = []

    for i, a in enumerate(assets):
        if not isinstance(a, dict):
            errors.append(f"assets[{i}] must be a dict")
            continue
        path = a.get("path")
        if not isinstance(path, str) or not path.strip():
            errors.append(f"assets[{i}].path is required (non-empty string)")
        else:
            if not Path(path).exists():
                warnings.append(f"assets[{i}].path does not exist yet: {path}")
        role = a.get("role", "other")
        if role not in ASSET_ROLES:
            errors.append(
                f"assets[{i}].role must be one of {sorted(ASSET_ROLES)}, got {role!r}"
            )

    constraints = brief.get("constraints") or {}
    if not isinstance(constraints, dict):
        errors.append("constraints must be a dict")
        constraints = {}
    else:
        dur = constraints.get("duration_seconds")
        if dur is not None and (
            not isinstance(dur, (int, float)) or float(dur) <= 0
        ):
            errors.append("constraints.duration_seconds must be a positive number")
        for dim in ("width", "height", "fps"):
            v = constraints.get(dim)
            if v is not None and not isinstance(v, (int, float)):
                errors.append(f"constraints.{dim} must be numeric when set")

    deliverable = brief.get("deliverable") or {}
    if not isinstance(deliverable, dict):
        errors.append("deliverable must be a dict")
    else:
        if not deliverable.get("bundle_path"):
            warnings.append("deliverable.bundle_path missing — agent must choose a .opm path")
        if not deliverable.get("export_path"):
            warnings.append("deliverable.export_path missing — agent must choose an export path")

    if not assets and constraints.get("no_generate"):
        errors.append("no assets and no_generate=true — nothing to cut")

    if brief.get("no_opinion") and not brief.get("defaults_applied"):
        warnings.append("no_opinion true but defaults_applied missing — re-run make_director_brief")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def _roles_present(assets: list[dict[str, Any]]) -> set[str]:
    roles: set[str] = set()
    for a in assets:
        if isinstance(a, dict):
            roles.add(str(a.get("role", "other")))
    return roles


def plan_session(brief: dict[str, Any]) -> dict[str, Any]:
    """Ordered step plan naming real MCP/Editor tools. Does not execute them."""
    v = validate_brief(brief)
    assets = list(brief.get("assets") or []) if isinstance(brief, dict) else []
    constraints = brief.get("constraints") or {} if isinstance(brief, dict) else {}
    deliverable = brief.get("deliverable") or {} if isinstance(brief, dict) else {}
    no_generate = bool(constraints.get("no_generate", False))
    roles = _roles_present(assets)

    steps: list[dict[str, Any]] = []

    def add(step_id: str, tool: str, purpose: str, **extra: Any) -> None:
        steps.append({"id": step_id, "tool": tool, "purpose": purpose, **extra})

    add("read_policy", "get_director_policy", "Load per-fragment quality gates")
    add("read_workflow", "get_film_workflow", "Load full session process + defaults")
    add(
        "doctor",
        "doctor",
        "Environment check (ffmpeg/Python/extras) — abort if ok=false",
    )

    asset_paths = [
        a.get("path") for a in assets
        if isinstance(a, dict) and a.get("path")
    ]
    fps = constraints.get("fps")
    width = constraints.get("width", 1920)
    height = constraints.get("height", 1080)
    if fps is None and asset_paths:
        add(
            "suggest_fps",
            "suggest_project_fps",
            "Pick 24/30/60 from user footage (do not inherit low gen fps)",
            params={"paths": asset_paths, "preference": "auto"},
        )
    if asset_paths and (
        constraints.get("width") is None or constraints.get("height") is None
        or (isinstance(width, (int, float)) and width >= 2560)
        or (isinstance(height, (int, float)) and height >= 1440)
    ):
        add(
            "suggest_resolution",
            "suggest_project_resolution",
            "Pick 720p–4k from sources; refuse native-4k claim if sources smaller",
            params={"paths": asset_paths, "preference": "auto"},
        )
    if asset_paths and (
        fps is not None
        or (isinstance(width, (int, float)) and width >= 1920)
    ):
        add(
            "check_delivery",
            "check_delivery_limits",
            "Gate: warn if requested fps/res exceeds source material",
            params={
                "paths": asset_paths,
                "fps": fps,
                "width": width,
                "height": height,
            },
        )
    add(
        "create_project",
        "create_project",
        "Open a new .opm bundle at recommended or constraint fps/resolution",
        params={
            "bundle_path": deliverable.get("bundle_path") or "<choose .opm path>",
            "fps": fps if fps is not None else 30,
            "width": width,
            "height": height,
        },
    )

    if assets:
        add(
            "analyze_assets",
            "analyze_asset",
            "Asset cards: scenes, silence, motion, transition affinity, role_guess",
            assets=assets,
            note="Loop analyze_asset per file; cache under .opm/analysis/",
        )
        add(
            "plan_edit",
            "plan_edit",
            "EDL: silence/scenes, B-roll overlay cutaways, L-cut lead, pace target",
            params={
                "paths": asset_paths,
                "cut_silence": True,
                "prefer_scenes": True,
                "b_roll_mode": "overlay",
                "target_duration_seconds": constraints.get("duration_seconds"),
            },
        )
        add(
            "apply_edit_plan",
            "apply_edit_plan",
            "Apply reviewed EDL (import + place + transitions)",
            note="Agent may skip and place_from_file manually if plan needs rework",
        )
        add(
            "structure_cut",
            "place_after",
            "Refine order / overlays after auto EDL; optional transition_type",
            note="Base video track first; overlays later",
        )
        # User talking-head / a_roll: understand speech + cut dead air before polish
        if roles & {"a_roll", "vo", "b_roll"} or any(
            isinstance(a, dict) and str(a.get("path", "")).lower().endswith(
                (".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3", ".m4a", ".flac")
            )
            for a in assets
        ):
            add(
                "detect_scenes",
                "detect_scenes",
                "Shot boundaries on long video (PySceneDetect/ffmpeg); split/place per scene",
            )
            add(
                "understand_speech",
                "transcribe",
                "ASR on user footage (faster-whisper); optional caption_clip to burn SRT",
                note="write_srt + apply_effect subtitles, or caption_clip one-shot",
            )
            add(
                "cut_dead_air",
                "suggest_silence_cuts",
                "Get keep_ranges between silences; agent trims/splits from those numbers",
            )
            if roles & {"a_roll", "music", "vo"} or True:
                add(
                    "optional_stems",
                    "separate_stems",
                    "Optional: Demucs vocals/no_vocals for dialogue vs bed control",
                    note="Skip if no music bed conflict; needs demucs installed",
                )
    else:
        add(
            "no_assets",
            "generate",
            "No user assets — plan generated fragments from intent/defaults only",
            skip_if=no_generate,
        )

    gaps: list[str] = []
    if not no_generate:
        if "a_roll" not in roles and "b_roll" not in roles and not assets:
            gaps.append("video")
        if "vo" not in roles and "vo_ref" not in roles:
            # only suggest VO if intent mentions speech-like goals or no_opinion multi-beat
            if brief.get("no_opinion") or (brief.get("intent") or ""):
                gaps.append("speech")
        if "music" not in roles:
            gaps.append("music")
        if "sfx" not in roles and brief.get("no_opinion"):
            gaps.append("sfx")  # optional; agent may skip

        if gaps:
            add(
                "recommend_models",
                "recommend_generation_profile",
                "Pick local models for gap kinds",
                kinds=gaps,
            )
            add(
                "generate_gaps",
                "generate",
                "Fill media gaps only; each fragment: job_status → quality_check → "
                "make_contact_sheet → place_generated (or upscale/redo)",
                kinds=gaps,
            )

    add(
        "project_look",
        "apply_project_look",
        "One session look language across video clips (cinematic/warm_resolve/…)",
        params={"look": "cinematic" if brief.get("no_opinion") else "documentary"},
        optional_tools=["list_look_presets", "color_match_to_clip", "apply_effect"],
    )
    add(
        "color_match",
        "color_match_to_clip",
        "Pull non-hero shots toward first A-roll clip grade (after look)",
        note="Pick reference_clip_id from get_project_state; skip if single clip",
    )
    add(
        "suggest_mix",
        "suggest_mix",
        "Meter VO/music stems → gain dB + ducking params",
        optional_tools=["suggest_dialogue_chain", "detect_beats"],
    )
    add(
        "apply_mix",
        "apply_mix_plan",
        "Apply suggested gains + set_ducking(music, vo)",
        optional_tools=["set_ducking", "gain", "analyze_timeline"],
    )
    add(
        "review_cut",
        "review_cut",
        "Structural craft review: gaps, flash cuts, brightness jumps, missing duck",
    )
    add(
        "sequence_sheet",
        "make_sequence_contact_sheet",
        "Whole-cut mid-frame grid — judge pacing/continuity before export",
        params={"output_path": "<bundle>/review/sequence_sheet.png"},
    )
    add(
        "export",
        "export",
        "Write final file; prefer normalize_preset=streaming for -14 LUFS",
        params={
            "output_path": deliverable.get("export_path") or "<choose export path>",
            "normalize_preset": "streaming",
            "run_delivery_check": True,
        },
    )
    add(
        "verify_export",
        "delivery_check",
        "Honest delivery gate (LUFS/peak/geometry/quality_check); ok=false → fix or warn user",
        optional_tools=["normalize_loudness", "quality_check", "get_license_report"],
    )

    return {
        "workflow_version": WORKFLOW_VERSION,
        "brief_ok": v["ok"],
        "validation": v,
        "no_opinion": bool(brief.get("no_opinion")) if isinstance(brief, dict) else False,
        "defaults": brief.get("defaults_applied") if isinstance(brief, dict) else None,
        "steps": steps,
    }


def get_workflow() -> dict[str, Any]:
    """MCP payload: process text + defaults + empty brief template."""
    return {
        "version": WORKFLOW_VERSION,
        "workflow": WORKFLOW_MARKDOWN,
        "defaults": dict(DEFAULT_AESTHETIC),
        "asset_roles": sorted(ASSET_ROLES),
        "brief_template": make_brief(
            intent=None,
            assets=[],
            constraints={},
            deliverable={"bundle_path": None, "export_path": None},
        ),
    }
