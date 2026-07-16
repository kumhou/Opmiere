# Changelog

## 0.4.96 — 2026-07-17

### Added
- Desktop **Compact** lane height toggle

## 0.4.95 — 2026-07-17

### Added
- Desktop **SelShare** — select all clips on same media_id

## 0.4.94 — 2026-07-17

### Added
- Timeline clip **tooltips**: name, TC range, speed/gain/opacity

## 0.4.93 — 2026-07-17

### Added
- Generate **steps / w / h** inputs → `/api/generate` params

## 0.4.92 — 2026-07-17

### Added
- OpenShot adapter **v4**: blur, color brightness, fade alpha ramps
- Test: `tests/test_openshot_adapter_v4_104.py`

## 0.4.91 — 2026-07-17

### Added
- Pro panel **collapse** toggle + **Doctor** full dump button
- `#pro-body` collapsible container

## 0.4.90 — 2026-07-17

### Added
- Desktop **Prep2** — prepare_for_export (fill gaps / clear empty)
- Milestone **0.4.90**: deep craft dual-surface complete

## 0.4.89 — 2026-07-17

### Added
- Desktop **Stems** (demucs) + **Frm** extract_frame from bin media

## 0.4.88 — 2026-07-17

### Added
- Desktop **RT?** / **RT↓** / **RT@** room tone pipeline

## 0.4.87 — 2026-07-17

### Added
- Desktop **Asset?** — load_asset_analysis cache hit

## 0.4.86 — 2026-07-17

### Added
- Desktop **SheetM** — make_contact_sheet on bin media file

## 0.4.85 — 2026-07-17

### Added
- Desktop **MkClr** — set_marker_color_batch

## 0.4.84 — 2026-07-17

### Added
- Desktop **RipRng** — ripple_delete_range on work I/O

## 0.4.83 — 2026-07-17

### Added
- Desktop **Xf1** / **Xf1✕** add_transition / remove_transition on selection

## 0.4.82 — 2026-07-17

### Added
- Desktop **Slug** / **Slug@** ensure_slug_media (+ place @ playhead)

## 0.4.81 — 2026-07-17

### Added
- Deep craft APIs: gain/opacity get, trim_clip, slug, transitions, ripple range, marker color batch, media contact sheet, keep_ranges, room tone, stems, extract_frame, prepare_for_export
- Desktop **G/O** refresh + **TrimSrc**
- Test: `tests/test_desktop_deep_craft_103.py`

## 0.4.80 — 2026-07-16

### Added
- Desktop **Lnk±** offset_linked audio peers; **Asset** analyze_asset card
- Milestone **0.4.80**: craft/mix/delivery dual-surface complete

## 0.4.79 — 2026-07-16

### Added
- Desktop **ExpRng** / **PxRng** — export_range + preview_range from I/O

## 0.4.78 — 2026-07-16

### Added
- Desktop **Tx?** cached transcript + **Caption** (ASR burn-in)

## 0.4.77 — 2026-07-16

### Added
- Desktop **Limits** — check_delivery_limits for honest fps/res claims

## 0.4.76 — 2026-07-16

### Added
- Desktop **Fmt?** — suggest project fps + resolution from bin

## 0.4.75 — 2026-07-16

### Added
- Desktop **Share?** (clips_sharing_media) + **After** (place_after bin)

## 0.4.74 — 2026-07-16

### Added
- Desktop **Sil?** / **Sil✓** — apply_silence_to_clip dry-run / apply

## 0.4.73 — 2026-07-16

### Added
- Desktop **ClrMatch** — grade selection toward first selected clip

## 0.4.72 — 2026-07-16

### Added
- Desktop **DetBeat** / **Mix?** (detect_beats + suggest_mix)

## 0.4.71 — 2026-07-16

### Added
- **Craft API surface**: looks, encode_status, beats, mix, color_match, silence, place_after, fps/res suggest, delivery limits, transcript, caption, range export, offset_linked, asset analyze
- Desktop **Looks** / **Enc**
- Test: `tests/test_desktop_craft_api_102.py`

## 0.4.70 — 2026-07-16

### Added
- Milestone **0.4.70**: Pro panel complete (agent → analyze → interchange → export → craft)
- Poll uses POST `/api/generate/status` as well as GET job
- Help grid: Preflight / Agent finish / Generate note
- README Status 0.4.70

## 0.4.69 — 2026-07-16

### Added
- Desktop **SRT** from markers (chapter-like cues)

## 0.4.68 — 2026-07-16

### Added
- Desktop **Px✕** invalidate proxy + **Recent∅** clear recent

## 0.4.67 — 2026-07-16

### Added
- Desktop **Beats** + **Snaps** inventory

## 0.4.66 — 2026-07-16

### Added
- Desktop **Del trk** + **Hard cut** (clear transitions)

## 0.4.65 — 2026-07-16

### Added
- Desktop **Still** (playhead) + **Aud out** mix export

## 0.4.64 — 2026-07-16

### Added
- Desktop **FCPXML** / **OTIO** interchange export

## 0.4.63 — 2026-07-16

### Added
- Desktop **Silence?** / **Scenes** on bin media

## 0.4.62 — 2026-07-16

### Added
- Desktop **Analyze TL** / **Analyze A** (`/api/analyze/*`)

## 0.4.61 — 2026-07-16

### Added
- **Pro agent API surface**: preflight/finish, analyze, silence/scenes, FCPXML/OTIO,
  still/audio export, track delete, hard_cut_all, batch_relink, split_at_beats,
  snap_points, preview invalidate, recent clear, write_srt, normalize_file
- Desktop **Pro / Agent**: Preflight + Agent finish
- Test: `tests/test_desktop_agent_pro_101.py`
## 0.4.60 — 2026-07-16

### Added
- **Generation HTTP API** (dual surface with MCP):
  `POST /api/generate`, `GET /api/generate/job/{id}`,
  `POST /api/generate/status`, `POST /api/place_generated`,
  `POST /api/quality_check`, `GET /api/license_report`
- Desktop **Generate** panel: kind + prompt, Gen / Poll / Place @ PH, QC, Licenses
- Test: `tests/test_desktop_generate_100.py` (mock provider)

## 0.4.59 — 2026-07-16

### Added
- **OpenShot adapter v3**: speed → `time_remap` + speed-aware fallback seek; crop
  fractions → Crop effect when available
- Status **comfy** pill from doctor `check_comfy=true`
- Ruler **TC ticks** (1s major, labels)
- Clip menu **Match frame**
- Test: `tests/test_openshot_adapter_v3_099.py`

## 0.4.58 — 2026-07-16

### Added
- **OpenShot adapter v2**: map opacity / rotate / overlay transform into plan;
  runtime applies alpha, rotation, scale, location (best-effort Keyframes)
- Plan reports `mapped` + `adapter_version`; OS plan UI shows summary
- **Clip context menu** (right-click): rename, mute, razor, copy, dup, delete
- Product shell copy: **API dogfood** (HTML probe demoted); program empty text
- Test: `tests/test_openshot_adapter_098.py`

## 0.4.57 — 2026-07-16

### Added
- Single-clip paths: gain / mute / opacity / speed / fades when selection=1
- **Ripple Del** single → `/api/ripple_delete` (now returns `timeline`)
- **Proxy** Shift-click force rebuild via `/api/preview/build`
- **Export I/O** falls back to core `/api/export_work` with path prompt
- Grade: **Glow** / **Ken** Burns
- Test: `tests/test_desktop_single_api_097.py`

## 0.4.56 — 2026-07-16

### Added
- Drag **move** commits via `/api/clip/layout` (atomic + quick preview)
- Single-clip **rename** → `/api/clip/meta`; sel-card double-click rename
- Inspector fades from `GET /api/clip/fades/{id}`
- Grade extras: **Sharp / Warm / Cool / Title** (text lower-third)
- **OS plan** / **OS frame** path-C diagnostics
- Test: `tests/test_desktop_layout_os_096.py`

## 0.4.55 — 2026-07-16

### Added
- **Grade FX** row: +Br / +Ct / +Sat / Vig / Blur / Grain / Vintage via `/api/clips/effect`
- **Px↻** quick `preview/refresh` (Shift = full rebuild)
- **State** dumps `/api/project/state` into Review
- Go-to TC uses core `/api/tc/parse` + `/api/tc/format` (local fallback)
- Test: `tests/test_desktop_grade_tc_095.py`

## 0.4.54 — 2026-07-16

### Added
- **Trim I/O**: selection → `/api/clip/trim_range` (I/O work area, normal|ripple)
- **Proxy 1**: single bin media proxy via `/api/media/proxy`
- **Style assets**: list LUTs / audio beds (`/api/style_assets`)
- **Keyframes**: review strip from `/api/preview/keyframes` + click-to-seek thumbs
- README status → 0.4.54; install messaging prefers desktop + Core API
- Test: `tests/test_desktop_keyframes_trim_094.py`

## 0.4.53 — 2026-07-16

### Added
- **Brief** director brief + session plan (intent + bin assets)
- **Workflow** film session doc dump in Review
- **Proxies** build all bin media proxies
- Help `?` merges core `/api/help/keymap`
- Marker list double-click rename; dirty pill sync via `/api/dirty`
- Marker next/prev uses `/api/markers/near`
- Test: `tests/test_desktop_agent_workflow_093.py`
## 0.4.52 — 2026-07-15

### Added
- **Xfade all / clr**: apply or clear cross-dissolves on track cuts
- **Rm empty** tracks, **Trk name**, **Append** bin media to track end
- **Plan edit** from bin paths, **Look** project grade from style select
- Test: `tests/test_desktop_xfade_plan_092.py`
## 0.4.51 — 2026-07-15

### Added
- **Organize** panel: mix snapshot, find/close-all gaps, select I/O / color / link
- **Shot##** batch rename, **Blk@PH** move_block to playhead
- **Trk↑/↓** reorder track of selection, **Mk±** shift markers 15f
- Test: `tests/test_desktop_organize_091.py`
## 0.4.50 — 2026-07-15

### Added
- **Cut templates** (talking_head / short_form / interview / vlog) from bin video paths
- **Finish** delivery (prepare + export + check → export dir)
- **Find ASR** search cached transcripts (click hit seeks)
- **Replace** clip media from bin selection (stretch)
- **Copy→trk** clone selection onto a new same-kind track
- **Mk in** import YouTube chapter markers
- Test: `tests/test_desktop_template_finish_090.py`
## 0.4.49 — 2026-07-15

### Added
- **Crop presets**: 1:1 (1080²), 9:16, 4:3 center crop
- **PiP**: top-right / bottom-left overlays + Full (clear position)
- Test: `tests/test_desktop_crop_pip_089.py`
## 0.4.48 — 2026-07-15

### Added
- **Import EDL / Cutlist** (`Imp EDL` / `Imp CSV`) — Tauri path or browser file text
- **ASR** transcribe bin/selection media (`[transcribe]`)
- **Media?** online/offline status dump
- **Duck / Un-duck** music under VO (2 audio tracks)
- Test: `tests/test_desktop_import_duck_088.py`
## 0.4.47 — 2026-07-15

### Added
- **Filler plan/apply** (desktop): `Filler?` dry-run ASR plan, `Filler✓` apply
  (`POST /api/filler`; needs `[transcribe]` extra / faster-whisper)
- Test: `tests/test_desktop_filler_087.py`
## 0.4.46 — 2026-07-15

### Added
- **EDL / Cutlist** export buttons → desktop export dir (CMX EDL + CSV)
- **Rotate** −90/+90/180 + **Reset XF** on selection
- **Relink←bin**: single-click select media, relink timeline selection
- `export_dir` lists `.edl/.csv/.json` as well as `.mp4`
- Test: `tests/test_desktop_interchange_086.py`
## 0.4.45 — 2026-07-15

### Added
- **Dirty guards**: Close asks stay/save/discard; Open/New/Demo/Recent warn if dirty
- **Auto-proxy** (default on): debounced `preview/ensure` after import/place/razor/delete
- Test: `tests/test_desktop_dirty_proxy_085.py`
## 0.4.44 — 2026-07-15

### Added
- **Detach A**: split selected video audio onto an A track (linked)
- **Auto-link**: link V/A clips that share the same start
- **Fit fill**: rate-stretch selection to next clip gap
- **Swap**: swap timeline starts of two selected clips
- Test: `tests/test_desktop_craft_av_084.py`
## 0.4.43 — 2026-07-15

### Added
- **Zoom to selection** (`Z` / Sel) — fit selection span in view
- **Fit sequence** (`Shift+Z` / Fit) — reset to 1× overview
- Test: `tests/test_desktop_zoom_fit_083.py`
## 0.4.42 — 2026-07-15

### Added
- **Magnetic time edits** (desktop):
  - **Ripple nudge**: clip + later on track — buttons ≪/≫, `Ctrl+Alt+←/→`
  - **Alt+←/→** plain nudge selection (±1 / Shift±5)
  - **Insert time** at playhead on all tracks: +15f / +1s, `[` / `]`
  - **Cut I/O**: `extract_time` I/O range on all tracks (ripple)
- Help overlay updated
- Test: `tests/test_desktop_magnetic_082.py`
## 0.4.41 — 2026-07-15

### Added
- **Insert / Overwrite** place mode for bin drag + double-click place
  - checkbox `Overwrite`; toggle with `.`
  - `mode=overwrite` lifts target range before place (core `place_media`)
- Test: `tests/test_desktop_edit_mode_081.py`
## 0.4.40 — 2026-07-15

### Added
- **Marquee select**: drag empty timeline lane space to rubber-band select clips
  (Shift/Ctrl additive)
- **Program fullscreen**: FS button + **Shift+F** (Esc exits)
- **Home / End**: seek sequence start / end
- Test: `tests/test_desktop_marquee_fs_080.py`
## 0.4.39 — 2026-07-15

### Added
- **Bin → timeline drag**: drag media row onto a track lane to place at drop x
  (kind-aware track remap; insert mode)
- Test: `tests/test_desktop_bin_drag_079.py`
## 0.4.38 — 2026-07-15

### Added
- **Media bin thumbnails** (desktop): video/image poster via `/api/media/{id}/thumb.jpg`
- **Timeline waveforms**: auto-load `POST /api/waveform` peaks for clips with audio; canvas paint
- Test: `tests/test_desktop_thumbs_waves_078.py`
## 0.4.37 — 2026-07-15

### Added
- **Close project**: `POST /api/project/close` (+ optional save); desktop **Close** / **Ctrl+W**
- **Go to timecode**: click program TC or **Ctrl+G** (HH:MM:SS:FF / seconds)
- Test: `tests/test_desktop_close_tc_077.py`
## 0.4.36 — 2026-07-15

### Added
- **Core lifecycle**: track owned core PID; `stop_core_api` + kill on Tauri `Exit`
  (only processes we spawned — never kills a pre-existing server)
- **Window title**: `Opmiere — <project>` when a bundle is open
- **Reopen last**: first empty session auto-opens the first viable recent project
- Permissions: `allow-stop-core-api`, `core:window:allow-set-title`
- Test: `tests/test_desktop_lifecycle_076.py`
## 0.4.35 — 2026-07-15

### Added
- **Auto-start core API** (Tauri): if `:8787` is down on refresh, invoke
  `ensure_core_api` → spawn `python -m opmiere.web.app` from
  `%LOCALAPPDATA%\Opmiere\install.json` or PATH
- Permission `allow-ensure-core-api`
- Test: `tests/test_desktop_ensure_core_075.py`

## 0.4.34 — 2026-07-15

### Added
- **Drag-drop import**: drop media onto Media panel
  - Tauri: OS paths via `onDragDropEvent` → `place_batch`
  - Browser: HTML5 FileList → `upload_place`
- **Ctrl+I** starts import (native picker / file input)
- Drop target highlight (`.drop-active`)
- Test: `tests/test_desktop_drop_import_074.py`

## 0.4.33 — 2026-07-15

### Added
- **Native media import** (Tauri): Import uses multi-file dialog + `POST /api/place_batch`
  (absolute local paths, no re-upload copy into browser FormData)
- Browser / Vite-only still uses hidden file input → `/api/upload_place`
- Test: `tests/test_desktop_native_import_073.py`

## 0.4.32 — 2026-07-13

### Added
- **Windows packaging**: NSIS installer target for Tauri shell
  - `scripts/build-desktop.ps1` (MSVC vcvars + `tauri build --bundles nsis`)
  - `npm run tauri:build` in `ui-desktop/`
  - Bundle metadata (publisher, description, currentUser install)
- Docs: release artifact paths + runtime note (Python API still separate)

## 0.4.31 — 2026-07-13

### Added
- **Native file dialogs** (Tauri): Open = folder picker, New = save-as path
  - `@tauri-apps/plugin-dialog` + `tauri-plugin-dialog` + `dialog:default` capability
  - Browser / Vite-only dev still falls back to `window.prompt`
- **Exp dir** uses `@tauri-apps/plugin-opener` to open export folder when available
- Test: `tests/test_desktop_dialog_fallback_071.py` (prompt-path helpers via HTTP open/create)

## 0.4.30 — 2026-07-13

### Added
- **Clip search** box → select hits via `clips/search`
- **Stabilize** selection
- **Describe** clip JSON dump
- **Mk out** YouTube chapters export
- **Exp dir**: `GET /api/desktop/export_dir` list (+ Tauri open if available)
- Test: `tests/test_desktop_search_stab_070.py`

## 0.4.29 — 2026-07-13

### Added
- **Freeze**: freeze-frame at playhead (15f) → `clip/freeze`
- **MatchΔ**: match duration (1st selected ← 2nd)
- **Dup I/O**: duplicate work-area range after sequence end
- **Prep exp**: `prepare_export`
- Test: `tests/test_desktop_freeze_dup_069.py`

## 0.4.28 — 2026-07-13

### Added
- **Slide±**, **Stretch ×0.5/×2**, **Stagger**
- **Rev trk / Rev clip**, **Fill gaps**
- Test: `tests/test_desktop_slide_stretch_068.py`

## 0.4.27 — 2026-07-13

### Added
- **Copy/Paste FX** + **Copy/Paste attributes** (session clipboard)
- **Effects list** for single selection
- **Review** (`review_cut`) + **Sequence sheet** (+ image preview)
- Test: `tests/test_desktop_fx_review_067.py`

## 0.4.26 — 2026-07-13

### Added
- **Timing**: Snap←/→, quantize 10f, align@playhead, slip ±5f, roll ±5f
- **Style** select + Apply → `POST /api/style` (selection or all)
- Test: `tests/test_desktop_timing_style_066.py`

## 0.4.25 — 2026-07-13

### Added
- **Name←file**: rename selection from media basename → `clips/name_from_media`
- **Dup trk**: duplicate track of selection → `track/duplicate`
- **Purge**: unused media (metadata) → `media/purge_unused`
- **Solo / Unmute**: clip solo + unmute all
- **J-cut / L-cut** buttons (needs linked A/V)
- Test: `tests/test_desktop_craft_065.py`

## 0.4.24 — 2026-07-13

### Added
- **Export presets** selector + `POST /api/desktop/export_preset`
- **Project stats** in inspector → `GET /api/project/stats`
- **Split@Mk**: razor at markers → `split_at_markers`
- Test: `tests/test_desktop_export_preset_064.py`

## 0.4.23 — 2026-07-13

### Added
- **Close gaps (G)** on all tracks → `close_gaps`
- **Lift / Extract** work area [In, Out)
- **Timeline zoom** (+/− / 0 / buttons), horizontal scroll
- **Keyboard help** overlay (`?`)
- Test: `tests/test_desktop_gaps_lift_063.py`

## 0.4.22 — 2026-07-13

### Added
- **Match frame (F)**: source frame at playhead → `clip/match_frame` + inspector card
- **Subclip (U)**: from work I/O if set, else middle half → `clip/subclip`
- **Markers from cuts** + clear all
- Test: `tests/test_desktop_match_subclip_062.py`

## 0.4.21 — 2026-07-13

### Added
- **Undo / Redo** buttons + history pill (`undo/redo` depth via `GET /api/history`)
- **Sel@ / D**: select clip(s) under playhead → `clips/at`
- **Duration report** in inspector → `GET /api/duration_report`
- Test: `tests/test_desktop_history_sel_061.py`

## 0.4.20 — 2026-07-13

### Added
- **Q / W** trim head/tail to playhead (respects Ripple Del) → `clip/trim_playhead`
- **I/O Sel**: work area from selection / single clip
- **Proxy** button → `preview/ensure`
- **Clear FX** on selection → `clip/clear_effects`
- Test: `tests/test_desktop_trim_proxy_060.py`

## 0.4.19 — 2026-07-13

### Added
- **Autosave** checkbox in product shell → `POST /api/autosave`
- Test: `tests/test_desktop_autosave_059.py`

### Fixed
- CI: optional demucs/faster-whisper tests no longer fail when extras are absent
  (`test_stems_optional`, `test_transcribe_entry_point_uses_whisper_model`)

## 0.4.18 — 2026-07-13

### Added
- **Validate** status pill + issue list → `GET /api/validate`
- **Project notes** textarea + Save → `GET/POST /api/notes` (from timeline.notes)
- Bundle path display in inspector
- Test: `tests/test_desktop_validate_notes_058.py`

## 0.4.17 — 2026-07-13

### Added
- **Selection card** in inspector (name / TC / speed / gain / opacity)
- **Opacity** presets → `clips/opacity`
- **Join** two selected clips → `clips/join`
- **Dissolve** cross-fade between two clips → `transition`
- Test: `tests/test_desktop_opacity_join_057.py`

## 0.4.16 — 2026-07-13

### Added
- **Rename** selection (R) → `clips/meta`
- **Gain** presets (−6…+6 dB) → `clips/gain`
- **Fade** in/out presets (0/6/12/24f) → `clips/fades`
- Test: `tests/test_desktop_meta_gain_056.py`

## 0.4.15 — 2026-07-13

### Added
- **Clip color**: palette swatches + **C** cycle → `clips/color` / `clips/color_cycle`
- **Clip speed**: 0.5× / 1× / 1.5× / 2× on selection → `clips/speed` (+ badge on clip)
- **Recent projects** list in inspector → `GET /api/recent` (click to open)
- Test: `tests/test_desktop_color_speed_055.py`

## 0.4.14 — 2026-07-13

### Added
- **Edit-point nav**: ↑/↓ or `;`/`'` or ◀Cut/Cut▶ — jump playhead on `snap_frames`
- Test: `tests/test_desktop_cuts_054.py`

## 0.4.13 — 2026-07-13

### Added
- **Export I/O**: `POST /api/desktop/export_work` → temp `export_work.mp4` for [In, Out)
- **Link / Unlink** selection (Ctrl+L / Ctrl+Shift+L) + link badge on clips
- **Redo**: Ctrl+Y / Ctrl+Shift+Z
- Test: `tests/test_desktop_export_link_053.py`

## 0.4.12 — 2026-07-13

### Added
- **Work I/O**: I / O set at playhead, X clear, Shift+I/O jump; range on marker ruler
- Display + buttons in timeline header
- Test: `tests/test_desktop_io_052.py`

## 0.4.11 — 2026-07-13

### Added
- **Snap** (on by default): drag/trim magnet to `snap_frames` (clip edges + markers, ±4f)
- **Ctrl+C / Ctrl+V / Ctrl+D**: copy · paste@playhead · duplicate
- Dirty pill in status bar (`timeline.dirty`)
- Test: `tests/test_desktop_snap_copy_051.py`

## 0.4.10 — 2026-07-13

### Added
- **Marker nav**: Shift+←/→ or ◀Mk/Mk▶ (wrap)
- **+V / +A** track buttons → `POST /api/track`
- **Home / End** seek to sequence start/end
- Test: `tests/test_desktop_nav_050.py`

## 0.4.9 — 2026-07-13

### Added
- **Markers**: M / Mark button → `POST /api/markers`; ruler ticks + inspector list; click seek, Alt+click delete
- **Clip mute**: Shift+M / Mute button → `POST /api/clips/mute` (toggle)
- **Track M/S/L** flags on lane labels → `track/mute`, `track/solo`, `track/lock`
- Test: `tests/test_desktop_mark_mute_049.py`

## 0.4.8 — 2026-07-13

### Added
- **New / Open** project (Ctrl+N / Ctrl+O): path prompt → `project/create` + seed V/A tracks, or `project/open`
- Test: `tests/test_desktop_project_048.py`

## 0.4.7 — 2026-07-13

### Added
- **Razor** (S / button): split all tracks at playhead → `POST /api/razor`
- **Save** (Ctrl+S / button) → `POST /api/save`
- **Media bin double-click**: place media at playhead → `POST /api/place_media`
- Test: `tests/test_desktop_edit_047.py`

## 0.4.6 — 2026-07-13

### Added
- **Media bin**: list project media via `GET /api/media`; **Import** multi-file → `POST /api/upload_place`
- **Ripple Del** toggle: delete + edge trim use ripple mode when checked
- Test: `tests/test_desktop_import_046.py`

## 0.4.5 — 2026-07-13

### Added
- **Multi-select**: click / Shift+click / Ctrl+A / Esc; selected clips drag → `clips/nudge`
- **Delete** selection (Del/Backspace) → `clips/delete`
- **Export** button → `POST /api/desktop/export` (`finish_delivery`, video-only fallback)

## 0.4.4 — 2026-07-13

### Added
- **Edge trim** handles on desktop clips → `POST /api/clip/edge_trim`
- **Cross-track drag** (drop on another same-kind lane) → `POST /api/clip/move_to_track`
- Demo project includes a second empty V track for reparent practice

## 0.4.3 — 2026-07-13

### Added
- **Timeline drag-move** in `ui-desktop` → `POST /api/clip/move` (+ quick proxy refresh)
- **Ctrl+Z undo** from product shell
- Verified **Tauri host full `cargo build`** with VS 2022 Build Tools

### Added (0.4.2)
- **Program play**: Space/K — proxy HTML5 play when proxy fresh; else stepped stills (~8fps)
- **Keyboard**: J/L ±5f, ←/→ ±1f, Space/K play·pause
- Play mode indicator; auto-ensure proxy before proxy play

## 0.4.1 — 2026-07-12

### Added
- **Program monitor** in `ui-desktop`: scrub + timeline click seek → `/api/preview/frame.jpg`
- **Demo project** API: `POST /api/desktop/demo_project` (lavfi cut for shell bootstrap)
- **Engine select**: auto / openshot / proxy / base
- API: `/api/preview/interactive`, `/api/preview/openshot_frame`, frame `engine=` param

## 0.4.0 — 2026-07-12

### Milestone
- **0.4 path C + product shell scaffold**: OpenShot interactive path + Tauri desktop host

### Decisions / docs
- **ADR** `docs/ADR_UI_AND_PREVIEW.md`: Tauri product shell; HTML probe-only; path C preview
- **Spike** `docs/SPIKE_LIBOPENSHOT_WINDOWS.md`: OpenShot embed / S2 sidecar

### Added
- **`PreviewSession`** + OpenShot S2 sidecar (seek→PNG; multi-clip plan + fallback)
- MCP/Editor: `preview_engine_status`, `openshot_frame_at`, `openshot_plan`
- **`ui-desktop/`** Tauri + Vite product shell (design tokens, core API status, timeline snapshot)
- **`scripts/dev-desktop.ps1`**: start API + `tauri dev`
- FastAPI **CORS** for Tauri/Vite origins

## 0.3.1 — 2026-07-11

### Milestone
- **0.3.x complete**: preview durability + agent default finish path + dogfood/CI

### Added
- **Preview proxy meta** (`review/preview_proxy.meta.json`): fingerprint survives reopen
- **`agent_finish_session`**: preflight → prepare → proxy → finish_delivery → save
- **`agent_preflight`**: includes proxy status + `next_steps` + `ready`
- **Dogfood**: `scripts/dogfood_agent_pipeline.py` + CI step

## 0.3.0 — 2026-07-11

### Milestone
- **UI shell complete** against `design-system/opmiere` checklist

### Added / Changed
- **Selection card** in Inspector (name, TC, speed, track, link, multi-count)
- **Toast** feedback host; **Ctrl+S** save shortcut
- **Link badge** on linked clips (`data-link` / `link_group`)
- Dirty pill tooltip; status bar marks shell 0.3.0 complete
- Docs: editor-shell.md checklist marked COMPLETE

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
