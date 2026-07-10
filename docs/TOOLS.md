# Opmiere tool surface (0.1.9)

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
| `create_project` / `open_project` / `save_project` / `get_project_state` / `get_timeline_view` | lifecycle + layout scrub |
| `suggest_project_fps` | auto\|24\|25\|30\|50\|60 |
| `suggest_project_resolution` | auto\|720p\|1080p\|1440p\|4k + feasibility |
| `check_delivery_limits` | honest fps/res vs sources |

## Media in

| Tool | Purpose |
|------|---------|
| `import_media` | `conform`, `fit=none\|contain\|cover`, optional `build_proxy` |
| `list_media_bin` / `ensure_media_proxy` / `ensure_all_media_proxies` | per-asset scrub proxies |
| `place_from_file` / `place_after` / `place_generated` / `place_batch` | place (+ batch) |
| `mix_view` | audio gains + ducking graph |
| `analyze_asset` | card: scenes, silence, motion, role |
| `detect_scenes` / `suggest_silence_cuts` / `transcribe` / `transcribe_media` / `separate_stems` | understand footage |
| `search_transcripts` | keyword search cached transcripts → timestamps |
| `suggest_filler_cuts` / `apply_keep_ranges` / `apply_filler_cuts` | filler 粗剪 (um/uh/那个…) |
| `plan_edit` / `apply_edit_plan` | EDL from cards |

## Edit / grade / audio

| Tool | Purpose |
|------|---------|
| `add_track` / `add_clip` / `trim` / `split` / `move` / `delete_*` | structure |
| `ripple_delete` / `close_gaps` / `detach_audio` | ripple edits + J/L sound split |
| `slip_clip` / `roll_edit` / `slide_clip` / `ripple_trim` | classic NLE trim suite |
| `set_clip_layout` / `edge_trim` | UI drag move+trim (one undo) |
| `refresh_preview_proxy` | rebuild scrub proxy when stale (`quick` for snappy UI) |
| `set_clip_gain` | clip volume dB (replaces prior gain) |
| `waveform_peaks` | audio peak envelope for timeline |
| `media_thumbnail` | media bin poster frame |
| `export_range` | full render then cut a time range deliverable |
| `apply_effect` / `add_transition` / `set_speed` / `set_position` | craft |
| `apply_project_look` / `color_match_to_clip` / `list_look_presets` | session look |
| `list_style_presets` / `apply_style_preset` / `list_style_assets` | film aesthetics + optional LUT/drone files |
| `list_cut_templates` / `apply_cut_template` | first-cut recipes (口播/短视频/访谈/vlog) |
| `apply_silence_to_clip` | dead-air keep ranges (dry_run default) |
| `finish_delivery` | review → export → delivery_check |
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
