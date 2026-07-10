# Changelog

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
