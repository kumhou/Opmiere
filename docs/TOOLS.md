# Opmiere tool surface (0.1)

Agent-facing tools live on **MCP** (`opmiere mcp` / `opmiere-mcp`) and mirror `Editor` methods. CLI: `opmiere doctor|version|web|mcp`.

## Session / policy

| Tool | Purpose |
|------|---------|
| `doctor` | ffmpeg, Python, extras, optional ComfyUI |
| `get_director_policy` | per-fragment quality loop |
| `get_film_workflow` | full process + defaults |
| `make_director_brief` / `validate_director_brief` / `plan_director_session` | brief → ordered steps |

## Project

| Tool | Purpose |
|------|---------|
| `create_project` / `open_project` / `save_project` / `get_project_state` | lifecycle |
| `suggest_project_fps` | auto\|24\|25\|30\|50\|60 |
| `suggest_project_resolution` | auto\|720p\|1080p\|1440p\|4k + feasibility |
| `check_delivery_limits` | honest fps/res vs sources |

## Media in

| Tool | Purpose |
|------|---------|
| `import_media` | `conform`, `fit=none\|contain\|cover` |
| `place_from_file` / `place_after` / `place_generated` | place |
| `analyze_asset` | card: scenes, silence, motion, role |
| `detect_scenes` / `suggest_silence_cuts` / `transcribe` / `separate_stems` | understand footage |
| `plan_edit` / `apply_edit_plan` | EDL from cards |

## Edit / grade / audio

| Tool | Purpose |
|------|---------|
| `add_track` / `add_clip` / `trim` / `split` / `move` / `delete_*` | structure |
| `ripple_delete` / `close_gaps` / `detach_audio` | ripple edits + J/L sound split |
| `apply_effect` / `add_transition` / `set_speed` / `set_position` | craft |
| `apply_project_look` / `color_match_to_clip` / `list_look_presets` | session look |
| `set_ducking` / `gain` / `suggest_mix` / `apply_mix_plan` / `suggest_dialogue_chain` | mix |
| `detect_beats` | music onset anchors |
| `analyze_audio` / `analyze_timeline` | ears |

## QA / deliver

| Tool | Purpose |
|------|---------|
| `quality_check` / `make_contact_sheet` | fragment gate |
| `review_cut` / `make_sequence_contact_sheet` | whole-cut craft |
| `ensure_preview_proxy` / `export_preview` / `frame_at` / `review_keyframes` / `preview_range` / `preview_proxy_status` | scrub eyes (proxy auto-stales) |
| `suggest_room_tone` / `extract_room_tone` / `place_room_tone` | fill digital silence after dialogue cuts |
| `export` | optional `normalize_preset`, default `delivery_check` in MCP |
| `normalize_loudness` / `delivery_check` | finish |

## Generation

| Tool | Purpose |
|------|---------|
| `generate` / `job_status` / `recommend_generation_profile` | local ComfyUI |
| `get_license_report` | restricted media |

See also: [AGENT_WARNINGS.md](AGENT_WARNINGS.md), `get_film_workflow()` markdown.
