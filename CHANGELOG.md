# Changelog

## Unreleased

- Preview: `ensure_preview_proxy` cache hit, `review_keyframes` 0–100%, web proxy fresh/stale badge + timecode
- `preview_range`, room tone fill (`place_room_tone`)
- Edit craft: `ripple_delete`, `close_gaps`, `detach_audio` (J/L-cut timing)

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
