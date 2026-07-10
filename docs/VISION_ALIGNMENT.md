# Vision alignment — external review vs Opmiere 0.1.x

A senior developer’s product framing (decoupled timeline JSON, MCP tools,
deterministic engine vs creative agent, style-as-parameters) is **the same bet
Opmiere already made**. Gaps are mostly product depth, not a wrong core.

## Already aligned

| Their requirement | Opmiere today |
|-------------------|---------------|
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

## Partial / next

| Gap | Status | Direction |
|-----|--------|-----------|
| Film **style preset library** (李安×恐怖 = param blend) | Look presets only | **`style_presets` JSON + apply/blend** (this release) |
| **Proxy media bin** for scrub | Timeline proxy yes; per-asset proxy no | Import-time low-res proxy later |
| **Semantic search** “找到我说但是” | ASR yes; search index no | Transcript index + search tool |
| **One-click AI 粗剪** filler words | Silence only | ASR + filler lexicon → ripple_trim plan |
| **CUDA / NVENC** export | libx264 only | **NVENC when available** (this release) |
| **Tauri/Electron dual UI** | FastAPI minimal web | Keep Python core; shell later (Tauri preferred) |
| Realtime filter scrub | Proxy frames | libopenshot/MLT still open |

## Disagreements / nuances

1. **“JSON is the database”** — yes; but mutations must stay behind `Editor`
   (undo, validation). Agents must not hand-edit `project.json` mid-session.
2. **“Avoid multiple FFmpeg runs”** — true for *delivery*. Preview/proxy and
   conform re-encodes are intentional extra passes; delivery path is one graph.
3. **Full CUDA filter_graph** — brittle with text/xfade/amix. Practical win is
   **NVENC encode + optional hw decode**, not rewriting every filter in CUDA.
4. **Style fusion** — Agent should **retrieve and blend local presets**, not
   invent LUTs. Human-tuned 5–10 styles beat freeform “李安滤镜” guesses.
5. **Stack** — Keep **Python Editor/MCP** as brain+hands; Tauri/web is a
   viewport. Rewriting core in Node for MCP is unnecessary churn.

## MVP map (their 3 steps → ours)

1. MCP timeline contract → **done (0.1)**  
2. Hand-tuned style files → **style_presets (0.1.2)**  
3. Squeeze 3070 → **NVENC export + doctor reports it**  

Proxy bin + filler 粗剪 + semantic search are the next product wedges after that.
