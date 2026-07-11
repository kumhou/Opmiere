# Changelog

## 0.2.34 — 2026-07-11

### Changed
- **UI shell v6**:
  - **Marquee select** clips by drag on empty lane area
  - Track header redesign with active **M/S/L** states
  - Auto-load audio **waveforms** for clips with audio
  - Zoom **+/−** buttons; stronger wave opacity
  - Fix broken track-lane class template escapes

## 0.2.33 — 2026-07-11

### Changed
- **UI shell v5**:
  - Right-click **context menu** on clips (mute, detach, split, copy, attrs, info, match, ripple delete)
  - Double-click clip → focus inspector
  - Video/audio **track heights**; hide clip labels when too narrow
  - Empty timeline CTA pointing at media drop

## 0.2.32 — 2026-07-11

### Added
- **`POST /api/upload_place`**: multipart upload → place on timeline (browser drag-drop / file picker)
- **UI shell v4**:
  - Drop zone on media panel (+ click to browse)
  - Drag to resize media / inspector column widths (`localStorage`)
  - Program **FS** fullscreen preview (Esc to exit)

## 0.2.31 — 2026-07-11

### Changed
- **UI shell v3**:
  - Bottom **key hint** strip (Space / JKL / I O / Q W / …)
  - Inspector `<details>` open/closed state persisted
  - Scrollbar / bin hover / brand gradient polish

## 0.2.30 — 2026-07-11

### Changed
- **UI shell v2**:
  - Toggle **Media** / **Inspector** panels (persisted in `localStorage`)
  - Drag **split handle** between Program and Timeline to resize rows
  - Status bar + Play/Pause label sync
  - Clean single DOCTYPE/body document markup

## 0.2.29 — 2026-07-11

### Changed
- **UI shell v1**: full-viewport editor chrome from `design-system/opmiere`
  - Regions: topbar · media/project · program preview · inspector · timeline
  - Design tokens (slate/blue/amber, Inter + mono TC, dense spacing)
  - Craft tools grouped in collapsible inspector details
  - Amber playhead, primary selection, focus-visible rings
  - All prior control ids + JS behavior preserved

## 0.2.28 — 2026-07-11

### Added
- **`export_fcpxml`**: minimal FCPXML 1.9 skeleton (base video track)
- **`export_otio_json`**: simplified OTIO-like JSON timeline
- **`agent_preflight`**: one-shot media/validate/duration/history/stats

## 0.2.27 — 2026-07-11

### Added
- **`prepare_for_export`**: prepare_export + validate + media status preflight
- **`export_still`**: timeline frame → image
- **`hard_cut_all`**: strip transitions + repack
- **`batch_relink` / `clips_sharing_media`**: mass relink + impact list
- **`set_marker_color_batch`**: batch marker colors

## 0.2.26 — 2026-07-11

### Added
- **`set_work_area_from_clip` / `set_work_area_from_selection`**
- **`markers_from_cuts` / `shift_markers` / `clear_markers`**
- **`solo_clip` / `unmute_all_clips`**: clip-level isolate
- **`set_clips_color_cycle`**: rotate bin colors
- **`duration_report`**: per-track duration census
- **`ripple_delete_range`**: alias for ripple extract_range

## 0.2.25 — 2026-07-11

### Added
- **`move_block`**: rigid selection move to target frame
- **`set_clips_gain` / `set_clips_opacity`**: batch audio/alpha
- **`validate_timeline`**: gaps/overlaps/transition diagnostics
- **`extract_range`**: multi-track extract (ripple optional)
- **`apply_transitions_on_cuts`**: batch cross-dissolve (etc.) on hard cuts
- **`list_media_status`**: online/offline media census
- **`name_clips_from_media`**: name clips from media basenames
- **`snap_clip`**: prev_end / next_start / zero
- **`split_at_beats`**: razor track on detected beat frames
- **`quantize_clips`**: snap starts/ends to frame grid
- **`export_audio`**: mixdown audio-only deliverable
- **`import_cutlist`**: CSV cutlist round-trip with export_cutlist
- Web: Validate, Xfade cuts, Name←media, Snap, Block→0, Extract I/O

## 0.2.24 — 2026-07-11

### Added
- **`stagger_clips`**: offset selection by index × step frames
- **`reverse_track_order`**: reverse clips on a track and repack
- **`clear_transitions`**: strip transition_in, restore hard-cut starts
- **`set_clips_fades`**: batch fade-in/out
- **`append_media`**: place media after last clip on track
- **`duplicate_range`**: copy overlapping clips in a time range
- Web: Stagger, Rev track, Dup I/O, Fade 6f, Clr xfade

## 0.2.23 — 2026-07-11

### Added
- **`join_clips`**: merge two adjacent same-media clips (contiguous source)
- **`set_clips_speed`**: batch playback speed [0.25, 4]
- **`trim_to_range`**: source-trim to timeline [start, end); `normal|ripple`
- **`auto_link_av`**: link unlinked V/A pairs sharing start (±tolerance)
- **`set_clips_meta`**: batch name/color
- Web: Join 2, Auto-link A/V, Sel 2×

## 0.2.22 — 2026-07-11

### Added
- **`lift`**: extract range without ripple (multi-track); leaves gap
- **`split_at_markers`**: razor all tracks at each marker (one undo)
- **`match_duration`**: stretch clip to match another clip's duration
- **`set_clips_color` / `clips_by_color`**: batch color chips + query
- **`export_cutlist`**: CSV/JSON cut list for agents
- **`place_media`**: three-point place from bin (`insert|overwrite`)
- Web: Lift I/O, Split@marks, Cutlist, Color sel, Match dur

## 0.2.21 — 2026-07-11

### Added
- **`fit_to_fill`**: rate-stretch clip to next clip start or explicit end_frame
- **`replace_edit`**: swap media keeping timeline start (`stretch|trim_end|trim_start|full`)
- **`copy_to_track`**: clone clip onto another same-kind track
- **`rename_clips`**: batch rename with `{n}` `{nn}` `{name}` `{media}` `{id}` `{track}`
- **`clips_in_range`**: list clips overlapping a timeline range
- **`import_edl`**: CMX-style EDL import (round-trip with `export_edl`)
- Web: Fit fill, Copy→V2, Rename Shot{nn}, Import EDL

## 0.2.20 — 2026-07-11

### Added
- **`describe_clip` / `search_clips`**: rich clip card + name/path search
- **`import_markers`**: YouTube chapters or CSV → timeline markers
- **`export_edl`**: simple CMX-style EDL of base video track
- **`trim_to_playhead(..., follow_links=)`**: Q/W on linked A/V (one undo)
- Web: Clip info, search, import marks, Export EDL; Q/W follow links

## 0.2.19 — 2026-07-11

### Added
- **`split_clip(..., follow_links=)`**: split linked A/V peers; new right-side link group
- **`j_cut` / `l_cut` / `offset_linked`**: picture-anchored audio lead/lag
- **`duplicate_track`**: clone track (+ clips)
- **`list_unused_media` / `purge_unused_media`**: bin hygiene
- **`project_stats`**: duration/counts/dirty census
- Web: J/L-cut (Shift+J/L), Dup track, Stats, Purge unused; S splits linked

## 0.2.18 — 2026-07-11

### Added
- **`stabilize_clip`**: deshake re-encode (replace media by default)
- **`export_markers`**: youtube chapters / csv / json
- **`copy_attributes` / `paste_attributes`**: speed, PiP, gain, fades, opacity
- Web: Stabilize, Copy/Paste attrs, Export marks, Sel track (A)

## 0.2.17 — 2026-07-11

### Added
- **Clip `link_group`**: linked A/V (or multi) selection groups
- **`link_clips` / `unlink_clips` / `linked_group`**
- **`nudge_clips` / `delete_clips` / `move_clip`**: `follow_links` (default on for nudge/delete)
- **`detach_audio(..., link=True)`**: auto-link picture+sound
- **`frames_to_tc` / `tc_to_frames`**: HH:MM:SS:FF helpers
- Web: Link / Unlink / Sel linked · Zoom fit (`\`) · Ctrl+L

## 0.2.16 — 2026-07-11

### Added
- **`swap_clips`**: exchange two clips' timeline starts
- **`move_track`**: reorder tracks (z-order for video overlays)
- **`set_track_name`**: optional track label on Project JSON
- **`set_clip_rotate` / `reset_clip_transform`**: rotate + clear PiP/crop/rotate/opacity
- Web: Swap 2, Track ↑/↓, rename, Rotate, Reset xform (R)

## 0.2.15 — 2026-07-11

### Added
- **`apply_effect_to_clips`**: one effect → many clips (one undo)
- **`set_clip_crop`**: replace crop effect (W×H px)
- **`find_gaps` / `close_all_gaps`**: gap report + pack all tracks
- **`remove_empty_tracks` / `list_tracks`**: track hygiene
- Web: Close all gaps (G), Find gaps, Rm empty, Crop, Batch blur

### Fixed
- **Undo/redo snapshots** deep-copy project JSON so in-place effect list edits roll back correctly

## 0.2.14 — 2026-07-11

### Added
- **`stretch_to`**: rate-stretch clip to target timeline duration (0.25–4×)
- **`marker_near`**: next / prev / nearest marker from a frame (optional wrap)
- **`clips_on_track`**: list clips for batch agent ops
- **`set_track_solo(..., exclusive=)`**: exclusive solo clears peers
- Web: Slide ;/' · Stretch → I/O · Next mark (Shift+M)

## 0.2.13 — 2026-07-11

### Added
- **`move_to_track`**: reparent clip to another same-kind track
- **`align_clips`**: relative group shift or stack starts
- **`copy_effects` / `paste_effects`**: session FX clipboard
- Web: Slip ,/. · Roll · Align → playhead · Copy/Paste FX · Move to track

## 0.2.12 — 2026-07-11

### Added
- **`trim_to_playhead`**: Q/W-style head/tail trim (ripple|normal)
- **`clear_clip_effects` / `list_clip_effects`**: strip grade/FX (optional type filter)
- **`list_export_presets` / `export_with_preset`**: draft|streaming|youtube|broadcast|review
- Web: Q/W buttons + keys, Clear FX, export preset picker

## 0.2.11 — 2026-07-11

### Added
- **`opacity` effect** + `set_clip_opacity` / `get_clip_opacity` (0..1 alpha)
- **`make_subclip`**: range or work In/Out → new clip / clipboard (web U)
- **`history_status`**: undo/redo depth, dirty, clipboard, I/O
- **`update_marker`**: edit label / color / frame

## 0.2.10 — 2026-07-11

### Added
- **`paste_clip(mode=)`**: `insert` (default) or `overwrite` (lift range then paste, one undo)
- Web: Overwrite paste (Ctrl+Shift+V), **J/K/L** shuttle on proxy (reverse/stop/forward speeds)

## 0.2.9 — 2026-07-11

### Added
- **`clips_at` / `match_frame`**: hit-test + source frame under playhead (Shift+F)
- **`set_clip_fades` / `get_clip_fades`**: fade in/out convenience (one undo)
- **`relink_clip`**: retarget clip to another project media
- Web: Detach audio, Match frame, fade controls, Relink; timeline exposes fade fields

## 0.2.8 — 2026-07-11

### Added
- **`freeze_frame`**: extract a still from a video clip and place as image hold
- **`reverse_clip`**: re-encode source range reversed; replace clip media by default
- Web: Freeze frame / Reverse buttons on selection

## 0.2.7 — 2026-07-11

### Added
- **Project notes**: `set_project_notes` / `get_project_notes` (persisted in `.opm`)
- **Keymap help**: `get_keymap_help` + web `?` overlay
- Web: speed slider, PiP x/y/scale, notes field; speed clamped to [0.25, 4]

## 0.2.6 — 2026-07-11

### Added
- **Clip labels/colors**: `set_clip_meta` (name + color chip); shown on timeline
- **Recent projects**: `list_recent_projects` (LOCALAPPDATA/Opmiere/recent.json)
- **Autosave / dirty**: `set_autosave`, mutation marks dirty; autosave writes after mutate
- Web: color palette, rename, recent open, dirty pill, autosave checkbox

## 0.2.5 — 2026-07-10

### Added
- **Ripple nudge**: `ripple_nudge` (clip + later on track)
- **Insert / extract time**: `insert_time`, `extract_time` (lift range + optional ripple)
- Web: Alt+←/→ ripple, Insert 15f, Extract I/O

## 0.2.4 — 2026-07-10

### Added
- **Multi-clip ops**: `nudge_clips`, `set_clips_muted`, `delete_clips(ripple=)`
- Web: Ctrl multi-select, Shift range on track, batch nudge/mute/ripple-del

## 0.2.3 — 2026-07-10

### Added
- **Track mute / solo / lock** on Project JSON; export respects mute/solo
- **Clip mute** (black/silence, keeps duration); lock blocks layout edits
- Web: per-track M/S/L buttons; clip mute toggle

## 0.2.2 — 2026-07-10

### Added
- **Clipboard**: `copy_clip` / `paste_clip` / `duplicate_clip` (session; effects preserved)
- **Work In/Out**: `set_in_point` / `set_out_point` / `export_work_area`
- Web: timeline zoom, I/O band, Ctrl+C/V/D, Export I/O

## 0.2.1 — 2026-07-10

### Added
- **Razor all tracks**: `split_all_at` / web `C` + Razor button
- **Link transition**: `link_transition` (cross_dissolve on hard cut); web X-fade
- **Snap points**: `snap_points` + timeline `snap_frames`; web drag snap toggle

## 0.2.0 — 2026-07-10

### Added
- **Gap fill for freeform edit**: `fill_track_gaps` (black/silence slug pads), `prepare_export`; `finish_delivery(prepare=True)` default
- **Timeline markers**: `add_marker` / `delete_marker` / `list_markers` on Project JSON
- Web: Fill gaps, Mark, keyboard (Space/←→/M/S/Del/[/]/F)

## 0.1.9 — 2026-07-10

### Added
- **`finish_delivery`**: review + export + delivery_check one-shot (honest `ok` / `delivery_ok`)
- **`apply_silence_to_clip`**: silence keep-ranges with safe apply (≥2 islands)
- Cut template `apply_silence` flag; dogfood `scripts/dogfood_template_pipeline.py` + CI step

## 0.1.8 — 2026-07-10

### Added
- **Cut templates**: `list_cut_templates` / `apply_cut_template` (talking_head, short_form, interview, vlog) — place + style + optional duck + hints
- **Style assets inventory**: `list_style_assets`, `resolve_style_asset` (LUT/audio under `assets/` or `OPMIERE_STYLE_ASSETS`)
- Web: template plan/apply; `assets/README.md` convention

## 0.1.7 — 2026-07-10

### Added
- **Batch import**: `place_batch` (auto kind by suffix, sequential append); web multi-path place
- **Mix console**: `mix_view` (gains + duck graph); web mix panel, duck set/clear, per-clip gain sliders
- `timeline_view` includes `mix` + per-track `duck`

## 0.1.6 — 2026-07-10

### Added
- **Waveform peaks**: `waveform_peaks` (ffmpeg mono PCM → envelope, cached); timeline canvas paint
- **Clip gain**: `set_clip_gain` / web gain slider; `gain_db` on `timeline_view`
- **Media bin thumbs**: `media_thumbnail` + `GET /api/media/{id}/thumb.jpg`; bin ASR button
- Web: Load waveforms, Close gaps (base V), gain control

## 0.1.5 — 2026-07-10

### Added
- **Timeline drag edit**: `set_clip_layout`, `edge_trim` (left/right, normal|ripple); web drag move + edge handles
- **Quick proxy refresh**: `refresh_preview_proxy(quick=True)` (~180p/ultrafast) after layout; web `/api/clip/layout` + `/api/preview/refresh`
- MCP: `set_clip_layout`, `edge_trim`, `refresh_preview_proxy`

## 0.1.4 — 2026-07-10

### Added
- **Editor shell UI**: proportional multi-track timeline, HTML5 proxy player (`/api/preview/proxy.mp4`), playhead seek, media bin panel, style apply, transcript search, filler dry/apply, undo/redo
- `Editor.timeline_view` / MCP `get_timeline_view` / `GET /api/project/timeline`
- Web APIs: media bin, style, filler, search, ripple_delete, proxy stream

## 0.1.3 — 2026-07-10

### Added
- **Media proxy bin**: `ensure_media_proxy` / `ensure_all_media_proxies` / `list_media_bin`; optional `import_media(build_proxy=True)`; `Media.proxy_path` under `proxies/`
- **Transcript search**: `transcribe_media` cache + `search_transcripts` keyword ranking (timestamps for “找到我说但是”)
- **Filler 粗剪**: `suggest_filler_cuts` / `apply_keep_ranges` / `apply_filler_cuts` (dry_run default); EN+ZH filler lexicon from word-level ASR

## 0.1.2 — 2026-07-10

### Added
- Film **style_presets** library + `apply_style_preset` blend (ang_lee, horror, wes_anderson, cyberpunk, thriller, documentary)
- **NVENC** delivery encode when available (libx264 fallback); doctor reports nvenc
- `docs/VISION_ALIGNMENT.md` — external review mapped in; **product = NLE**, director/style = hero feature

## 0.1.1 — 2026-07-10

### Added
- Preview: `ensure_preview_proxy` cache hit, `review_keyframes`, `preview_range`, web proxy badge
- Room tone: `suggest_room_tone` / `extract_room_tone` / `place_room_tone`
- Edit craft: `ripple_delete`, `close_gaps`, `detach_audio`, `slip_clip`, `roll_edit`, `slide_clip`, `ripple_trim`
- `export_range` segment deliverable
- Empty base-audio export + suppress embedded video audio when audio tracks have clips

## 0.1.0 — 2026-07-10

**Agent-native cut baseline** (not a consumer NLE).

### Added
- Asset intelligence: `analyze_asset`, fps/resolution suggestions, delivery limits
- EDL: `plan_edit` / `apply_edit_plan` (overlay B-roll, L-cut, J-cut black pad, beats)
- Delivery: `normalize_loudness`, `delivery_check`, `review_cut`, sequence contact sheet
- Look: project look presets, `color_match_to_clip`
- Mix: `suggest_mix`, `apply_mix_plan`, `suggest_dialogue_chain`, `detect_beats`
- Import: auto fps conform, optional `fit=contain|cover`, audio sample-rate conform
- Preview: `export_preview`, `frame_at`, proxy auto-invalidate on mutate
- Native Windows install: `scripts/install.ps1`, `uninstall.ps1`, `opmiere doctor`
- P3 web: doctor, review, look, delivery export, scrub
- Dogfood: `scripts/dogfood_pro_pipeline.py` + checklist gates
- Docs: `docs/TOOLS.md`, `docs/AGENT_WARNINGS.md`
- CI: GitHub Actions Windows + ffmpeg + pytest + dogfood

### Notes
- Cloud generation still deferred
- Realtime NLE scrub (libopenshot/MLT) not included — lightweight proxy only
- Version 0.1 means “agent can cut and honestly deliver”, not feature parity with Premiere
