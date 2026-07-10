"""Agent-director policy (ARCHITECTURE.md §5.10).

The tools for the loop already exist (generate / quality_check /
make_contact_sheet / upscale / place_generated). What's missing is not
capability — it's encoding the *decision order* somewhere an MCP agent
reliably reads before spending tokens on every frame. This module is that
encoding: get_director_policy MCP tool returns it verbatim; the MCP server
instructions point at it.

Deliberately NOT a combined accept/regenerate Editor method — that would
either force contact_sheet after every quality_check (defeating the free
gate) or duplicate generate/place_generated. Policy stays agent-side over
existing tools.
"""

from __future__ import annotations

# Versioned so agents and humans can tell which policy a session followed.
DIRECTOR_POLICY_VERSION = "1.0"

DIRECTOR_POLICY = """\
# Opmiere agent-director policy v{version}

You are directing a cut with Opmiere's tools. Quality is mostly *deterministic
tools + selective generation*, not "generate everything and hope."

## Before generating
1. `get_project_state` — know fps, resolution, track/clip ids.
2. Match video generation `frame_rate` to project fps (or place_generated fails).
3. Prefer deterministic tools (cut, color, curves, lut3d, ken_burns, text,
   transitions, gain, ducking, …) over regeneration for look/timing problems.
4. `recommend_generation_profile(kind)` when unsure which local model fits VRAM.

## Per generated fragment (image / video / speech / music / sfx)
1. `generate(kind, prompt, params)` → job id.
2. Poll `job_status` until `done` or `error` (never assume done).
3. **Free gate:** `quality_check(result_path)`.
   - Fail (black / frozen / blurry / silent as applicable) → regenerate.
     Do NOT open the contact sheet or burn vision tokens on a dead clip.
4. **Cheap eyes:** `make_contact_sheet(result_path, output_path)` for video
   (and useful for multi-beat motion). Inspect that one grid image.
5. **Decide (three questions):**
   - Does this shot carry the intended emotion / information?
   - Is composition / subject / motion usable?
   - Does it sit next to already-committed neighbors without a style jump?
6. **Act:**
   - Bad → regenerate (tighter prompt, same seed for continuity, or higher
     `model` tier). Draft is cheap; commit is expensive.
   - Good draft, want sharper still → `generate(kind="upscale",
     params={{"source_path": result_path}})` then place that result.
   - Good as-is → `place_generated(job_id, track_id, start)` (omit
     duration_frames for video/audio to use real probed length).

## After placing
- Harmonize looks with deterministic grade (`color`, `curves`, `lut3d`) rather
  than regenerating whole shots for small color drift.
- Audio: multi-track mix; `set_ducking` so music yields to voice; `analyze_audio`
  as ears (LUFS / silence / optional waveform) before export.
- Export → run `quality_check` on the export path; trust pixels, not "no error."

## Continuity (no frame-chaining yet)
- Shared prompt anchor words across related shots.
- Reuse seed when iterating the same shot.
- Finish with one grade language across the sequence.

## Cost discipline
- quality_check is free (ffmpeg). Always first.
- contact_sheet is cheap vision. Prefer it over many full-res frames.
- upscale beats full re-generate for "this draft is right, just soft."
- Cloud generation is out of scope unless the user explicitly asks.

## Anti-patterns
- place_generated before quality_check.
- Vision-inspecting a quality_check failure.
- One mega-generate instead of fragments + edit.
- Inventing effect/tool names not in apply_effect / the tool list.
""".format(version=DIRECTOR_POLICY_VERSION)


def get_policy() -> dict[str, str]:
    """Structured payload for the MCP tool / callers."""
    return {
        "version": DIRECTOR_POLICY_VERSION,
        "policy": DIRECTOR_POLICY,
    }
