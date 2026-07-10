# Opmiere tool surface (0.2.16)

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
| `finish_delivery` | prepare gaps → review → export → delivery_check |
| `fill_track_gaps` / `prepare_export` | black/silence pads or pack for base-track export |
| `add_marker` / `delete_marker` / `list_markers` | timeline markers |
| `split_all_at` / `link_transition` / `snap_points` | razor, xfade, snap targets |
| `copy_clip` / `paste_clip` / `duplicate_clip` | session clipboard; paste `mode=insert|overwrite` |
| `set_in_point` / `set_out_point` / `export_work_area` | work area export |
| `set_track_muted` / `set_track_solo` / `set_track_locked` | track M/S/L |
| `set_clip_muted` | clip mute (black/silence) |
| `nudge_clips` / `set_clips_muted` / `delete_clips` | multi-select batch ops |
| `ripple_nudge` / `insert_time` / `extract_time` | magnetic-style track time ops |
| `set_clip_meta` / `list_clip_colors` | clip name + color chips |
| `list_recent_projects` / `set_autosave` / `project_dirty` | recents + autosave |
| `set_project_notes` / `get_project_notes` / `get_keymap_help` | notes + shortcut help |
| `freeze_frame` / `reverse_clip` | still hold + reverse re-encode |
| `clips_at` / `match_frame` | hit-test + source frame (Match Frame) |
| `set_clip_fades` / `get_clip_fades` | fade-in / fade-out convenience |
| `set_clip_opacity` / `get_clip_opacity` | clip alpha 0..1 |
| `make_subclip` | subclip from range or work I/O |
| `history_status` | undo/redo depth + dirty + clipboard |
| `update_marker` | edit marker label/color/frame |
| `trim_to_playhead` | Q/W head|tail to playhead (ripple|normal) |
| `clear_clip_effects` / `list_clip_effects` | strip effects (optional types) |
| `list_export_presets` / `export_with_preset` | named delivery recipes |
| `move_to_track` | reparent clip to another same-kind track |
| `align_clips` | group shift or stack starts to a frame |
| `copy_effects` / `paste_effects` | session effects clipboard |
| `stretch_to` | rate-stretch to target timeline duration |
| `marker_near` | next / prev / nearest marker |
| `clips_on_track` | list clips on a track |
| `set_track_solo(..., exclusive=)` | exclusive solo on same kind |
| `apply_effect_to_clips` | one effect on many clips (one undo) |
| `set_clip_crop` | replace crop W×H (optional x/y) |
| `find_gaps` / `close_all_gaps` | gap report + pack all tracks |
| `remove_empty_tracks` / `list_tracks` | track hygiene |
| `swap_clips` | exchange two clips' starts |
| `move_track` / `set_track_name` | track z-order + label |
| `set_clip_rotate` / `reset_clip_transform` | rotate + clear layout transform |
| `relink_clip` | retarget clip to other project media |
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
