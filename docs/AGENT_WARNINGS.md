# Agent warnings — when you must tell the user

Opmiere will often *technically* succeed while the result is not honest professional delivery. Agents must surface these cases.

## Hard gates (do not claim “done / pro quality”)

| Situation | Tool signal | What to say |
|-----------|-------------|-------------|
| Requested fps &gt; source max | `suggest_project_fps` / `check_delivery_limits` warnings/errors | Not free quality; motion may step or need interpolation |
| Requested res &gt; largest source | `suggest_project_resolution` `feasible_native=false` / `errors` | Not native 4k/UHD; upscale only |
| `delivery_check.ok=false` | after export | Fix loudness (`normalize_loudness`) or lower claim; do not ship as final |
| `doctor.ok=false` | missing ffmpeg/python | Fix environment before a film session |
| `review_cut` severity=error | gaps, empty base | Fix timeline before export |
| Proxy `preview_proxy_status.fresh=false` | after edit | Rebuild `export_preview` before trusting scrub frames |

## Soft craft (warn, can continue)

| Situation | Signal | Guidance |
|-----------|--------|----------|
| Multi-audio, no ducking | `review_cut` `no_ducking` | `set_ducking(music, vo)` or `suggest_mix` → `apply_mix_plan` |
| Short flash clips | `short_clip` | Lengthen or intentional style note |
| Hard-cut luma jump | `brightness_jump` | dissolve or `color_match_to_clip` |
| B-roll on base after A-roll | plan_edit warning | Prefer `b_roll_mode=overlay` |
| Import re-encode | `origin.conformed` | Tell user source was fps/size/sample-rate converted (not lossless) |
| Intentional blur vs fail | `quality_check` blur | Artistic DOF can trip free gate — confirm with contact sheet |
| Dead air after silence cuts | digital black between VO | `place_room_tone` from same take; do not leave pure silence |

## Session order (do not freestyle)

1. `doctor` → abort if not ok  
2. `suggest_project_fps` / `suggest_project_resolution` / `check_delivery_limits`  
3. Place **user** assets before generation  
4. `quality_check` before `place_generated`  
5. `apply_project_look` / `color_match_to_clip` after structure  
6. `review_cut` + sequence sheet (+ optional preview)  
7. `export(..., normalize_preset="streaming")` → **`delivery_check` required**

## Anti-patterns

- Claiming native 4k/60fps from weaker sources  
- `place_generated` before `quality_check`  
- Generating B-roll before placing user’s A-roll  
- Trusting stale preview proxy after timeline edits  
- Skipping `delivery_check` because “ffmpeg exited 0”
