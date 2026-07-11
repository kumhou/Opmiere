# Vision alignment — external review vs Opmiere 0.1.x

## Product first

**Opmiere is a video editor** (agent-native NLE): timeline, multi-track A/V, trim craft,
effects, preview, honest delivery. That is the product.

The “导演–剪辑师” dual-layer story (style library, MCP → FFmpeg, agent as director) is a
**hero feature / workflow layer** on top of that editor — useful design input from external
review, not a redefinition of the product into “a director agent with a timeline bolted on.”

Ship priority stays editor-complete; style blend and director policy are differentiators,
not a license to underbuild classic NLE surfaces (proxy bin, scrub, filler cut, UI).

## What the external review got right (as feature design)

Decoupled timeline JSON, MCP tools, deterministic engine vs creative agent,
style-as-parameters — same bet Opmiere already made for the **agent path**. Gaps are mostly
product depth in the **editor**, not a wrong core.

## Already aligned (editor core)

| Requirement | Opmiere today |
|-------------|---------------|
| Timeline as single source of truth | `Project` JSON in `.opm` / `Editor` only mutator |
| UI and agent same surface | MCP ≈ `Editor` methods; web is thin client |
| Atomic edit APIs | split/move/trim/speed/effects/transitions + slip/roll/slide/ripple |
| Multi-track A/V | Base + overlay video/audio, ducking |
| Single filter_graph export | `FFmpegBackend` one-shot encode (not per-clip temp files) |
| Deterministic grade/look | `apply_effect`, looks, LUT, curves, ken_burns, … |
| Agent does not invent filters | Validated `KNOWN_*` vocabularies |
| ASR / captions | faster-whisper optional, `caption_clip` |
| Silence cut assist | `suggest_silence_cuts` / keep_ranges (not yet “one-click filler”) |
| Delivery honesty | `delivery_check`, fps/res limits, agent warnings doc |

## Hero feature status (director / style — not the whole product)

| Piece | Status | Role |
|-------|--------|------|
| Film **style preset library** (李安×恐怖 = param blend) | **0.1.2** `style_presets` + blend | Aesthetic pack, not the app |
| Director brief / session plan | `workflow` + `director_policy` | Ordered tool path for agents |
| **CUDA / NVENC** export | **0.1.2** when available | Perf for any export, agent or human |

## Editor depth (product roadmap)

| Gap | Status |
|-----|--------|
| **Proxy media bin** for scrub | **0.1.3** `ensure_media_proxy` / `list_media_bin` |
| **Transcript search** “找到我说但是” | **0.1.3** keyword cache search (not embeddings) |
| **One-click filler 粗剪** | **0.1.3** `suggest_filler_cuts` + `apply_filler_cuts` |
| **Dual UI surface** | Probe: FastAPI HTML shell (dogfood). Product: **Tauri** + WebView chrome; MCP external |
| Realtime filter scrub | Path **C**: prefer libopenshot (spike first); MLT fallback; FFmpeg proxy interim only |

## Disagreements / nuances

1. **“JSON is the database”** — yes; but mutations must stay behind `Editor`
   (undo, validation). Agents must not hand-edit `project.json` mid-session.
2. **“Avoid multiple FFmpeg runs”** — true for *delivery*. Preview/proxy and
   conform re-encodes are intentional extra passes; delivery path is one graph.
3. **Full CUDA filter_graph** — brittle with text/xfade/amix. Practical win is
   **NVENC encode + optional hw decode**, not rewriting every filter in CUDA.
4. **Style fusion** — retrieve and blend local presets; human-tuned 5–10 styles
   beat freeform “李安滤镜” guesses. Still one tool among many on the timeline.
5. **Stack** — Python Editor/MCP is the engine; Tauri is the human viewport (web tech for
   chrome/timeline OK). HTML `opmiere-web` is probe-only. Rewriting core in Node is churn.
   Full ADR: [ADR_UI_AND_PREVIEW.md](ADR_UI_AND_PREVIEW.md).
6. **Do not invert the pyramid** — NLE craft (import, cut, slip/roll, mix, export)
   is the base; “agent as director” is the hero path that uses that base.

## MVP map (their 3 steps → ours)

1. MCP timeline contract → **editor baseline (0.1)**  
2. Hand-tuned style files → **hero feature (0.1.2)**  
3. Squeeze 3070 → **NVENC export + doctor**  

0.1.4+ HTML dual-surface shell = probe. Product GUI = Tauri (ADR 2026-07-12).
Interactive preview = libopenshot preference + spike; no hybrid throwaway path.
