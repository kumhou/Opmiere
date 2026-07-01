# Opmiere — Architecture

> **Open Premiere** — an open-source, agent-native non-linear video editor for Windows.
> Humans edit with a GUI; AI agents (Claude Code, Cursor, any MCP client) drive the *same*
> editing engine through a Model Context Protocol server. Generative AI (image / video / audio)
> runs **locally on your own GPU first**, with **paid cloud APIs as an optional quality boost**.

Status: **v0.1 — design.** Nothing here is frozen except where marked **DECIDED**. This document is
the single source of truth for *why* the system is shaped the way it is.

---

## 1. Why this exists

> **North star.** The market generates a whole video in *one shot*. Opmiere instead builds a film from
> **many small, controlled generations, assembled with real editing craft and sound design** — directed
> end-to-end by a frontier LLM agent. The bet: a *directed, assembled* piece **beats a one-shot clip
> from an even stronger model**, because control, continuity, audio, and craft add quality that raw
> generation cannot — and it can run to any length. Every tool and abstraction in Opmiere exists to give
> that agent perfect hands and feet. This also fits the hardware: an 8 GB card struggles with one long
> big generation but handles short fragments fine — so the philosophy *and* the constraint point the
> same way.

Existing open-source NLEs (Shotcut, Kdenlive, OpenShot, Olive) are excellent editors but have **no
agent interface** — you cannot tell an LLM "cut the dead air, generate a B-roll clip of a sunrise,
drop it at 0:12, and color-match it to the previous shot." Palmier Pro (GPL-3.0, ~10k stars) proved
the agent-native NLE concept, but it is **macOS / Apple-Silicon only** and its generation leans on
**cloud APIs**. Opmiere's distinction is therefore *not* "open vs closed" — both are open source — but
**Windows + NVIDIA/CUDA, with local-GPU generation as the core capability, not a fallback**.

Opmiere targets the gap:

1. **Agent-native.** Every edit a human can do, an agent can do, through one shared operation API.
2. **Local-GPU generation as a first-class capability.** The explicit goal is to make a *modest* card
   (RTX 3070 / 8 GB) produce *high-quality* output by aggressively applying quantization + memory
   offload, trading generation *time* for *quality and model reach* — longer waits are acceptable.
   Cloud APIs remain pluggable providers for when the user wants speed or the absolute top tier.
3. **Windows-first, NVIDIA/CUDA.** The audience is ordinary creators priced out of Runway/Sora/Kling
   subscriptions who have a capable gaming GPU sitting idle. Both editors are open source; the
   differentiation is platform + depth of local generation.

---

## 2. Hardware baseline (the constraint that shapes everything)

Primary dev/reference machine: **NVIDIA RTX 3070, 8 GB VRAM, 32 GB RAM, Windows 11.**

8 GB VRAM is the *entry tier* for generative AI, and it dictates the product design:

| Task | Local on 8 GB | Verdict |
|------|---------------|---------|
| Image gen (SDXL, SD1.5) | comfortable | ✅ primary local path |
| Image gen (Flux, 12B) | needs GGUF quant, slow | ⚠️ usable |
| Video gen — LTX-Video | designed for consumer GPUs | ✅ primary local video path |
| Video gen — CogVideoX-2B / Wan-1.3B | GGUF + CPU offload | ✅ solid local path |
| Video gen — Wan-14B / Hunyuan (~13B) | GGUF Q4 + block-swap → 32 GB RAM | ⚠️ reachable, slow (minutes/clip) |

**Consequence (DECIDED):** local generation is a **first-class path, not a draft-only fallback**. With
the low-VRAM stack (§5.7) — GGUF / FP8 / SVDQuant quantization, CPU + block-swap offload into the
32 GB of system RAM, tiled VAE decode, memory-efficient attention, and step-distilled models — even
13–14B video models become *reachable* on an 8 GB card. The cost is paid in **time, not quality**,
which is JH's explicitly accepted trade. Cloud providers exist for when the user wants speed or the
very top tier. The architecture treats local and cloud generation as **interchangeable providers
behind one interface**, and **auto-selects the best local strategy for the detected VRAM** (§5.7) so
ordinary users never have to hand-assemble ComfyUI graphs.

---

## 3. Design principles

1. **API-first / headless core.** The core knows nothing about a GUI. The GUI and the MCP server are
   both *clients* of the same core operation API. This is what makes "agent can do anything the human
   can" true by construction, not by duplicated effort.
2. **Engine-independent project model.** Opmiere owns its own timeline data model as the source of
   truth. Render engines (FFmpeg, later libopenshot/MLT) are **pluggable backends** that the model is
   *compiled down to*. Swapping engines never changes the agent-facing surface.
3. **Everything a provider.** Generation backends (ComfyUI local, Replicate/fal/Runway/Kling cloud)
   implement one `GenerationProvider` interface. Render engines implement one `RenderBackend`
   interface. New capabilities = new plugin, not a rewrite.
4. **Agent-legible state.** The project model is designed to be read and mutated by an LLM: stable
   IDs, explicit units (frames + timebase, not vague "seconds"), flat addressable operations. It is
   *not* a GUI view-state that happens to be serializable.
5. **Async by default.** Generation takes seconds to minutes. Every long op is a job with an ID and a
   status, never a blocking call.

---

## 4. System layers

```
        ┌──────────────────────────────────────────────────────────────┐
        │                         CLIENTS                                │
        │                                                                │
        │   Human GUI  (web frontend, later)      AI Agents (MCP)        │
        │        │                                     │                 │
        └────────┼─────────────────────────────────────┼────────────────┘
                 │                                     │
                 ▼                                     ▼
        ┌──────────────────────────────────────────────────────────────┐
        │                     CORE OPERATION API                         │
        │   (the only way to mutate a project — one command surface)     │
        │                                                                │
        │   ProjectModel  ──►  Operations  ──►  undo/redo, events        │
        └───────┬───────────────────┬───────────────────┬───────────────┘
                │                   │                   │
                ▼                   ▼                   ▼
        ┌───────────────┐  ┌─────────────────┐  ┌────────────────────────┐
        │ RenderBackend │  │ GenerationProv. │  │ Media / asset store     │
        │  (pluggable)  │  │   (pluggable)   │  │  (.opm project bundle)  │
        │               │  │                 │  │                        │
        │ • FFmpeg  ◄─── now                  │  └────────────────────────┘
        │ • libopenshot │  │ • ComfyUI (local)                            │
        │   / MLT ◄ later│ │ • Replicate/fal/Runway/Kling (cloud)         │
        └───────────────┘  └─────────────────┘
```

---

## 5. Technology decisions

### 5.1 Core language: **Python** — DECIDED
- The entire local-generation ecosystem (ComfyUI, diffusers, torch) is Python. Zero-friction integration.
- The official MCP SDK, `ffmpeg` tooling, and NLE libraries (libopenshot, MLT) all have Python bindings.
- Largest contributor pool, and it overlaps exactly with the AI-tinkerer audience who will adopt and
  extend an agent-native AI video tool.
- Python 3.10 already installed on the reference machine.
- The usual Python weaknesses are dodged: heavy ML deps live in a *separate* ComfyUI process; the
  performance-critical compositing is done by the render engine (C/C++), not Python.

### 5.2 Render engine: **FFmpeg now, libopenshot/MLT later** — DECIDED (staged)
- **Phase 0–2 use FFmpeg directly** (already installed, fully scriptable) for the export/render path:
  trim, concat, overlay, mix, burn-in. This is enough to prove the whole *agent-edits-then-renders*
  loop headlessly, without fighting Windows builds of MLT's Python bindings.
- **Phase 3+ adds an interactive backend** (libopenshot preferred — it *is* an NLE library with clean
  Python bindings and Windows binaries; MLT as alternative) for real-time preview and frame-accurate
  scrubbing, which FFmpeg alone does not give cheaply.
- Both sit behind the `RenderBackend` interface; the project model never knows which is active.

### 5.3 Generation: **ComfyUI (local) + cloud aggregators** — DECIDED
- **Local:** run ComfyUI as a separate local server; submit templated workflow graphs over its
  HTTP/WebSocket API. Isolates the multi-GB torch/CUDA stack from the app; lets power users reuse an
  existing ComfyUI install and their own models/LoRAs.
- **Cloud:** start with an aggregator (Replicate or fal.ai) to reach many models (Kling, Runway, Sora,
  Flux, ElevenLabs) through one billing + one adapter; add direct providers later.
- All behind `GenerationProvider`; the user picks local vs cloud per generation.

### 5.4 GUI: **web frontend, deferred to Phase 3** — DECIDED (direction), details open
- A web (TypeScript) frontend talking to the Python core over WebSocket is the pragmatic choice:
  timelines, drag-drop, waveforms, thumbnails are well-trodden in web tech, and it makes the GUI *just
  another client of the core API* — which is exactly the agent-native architecture we already need.
- Desktop packaging (Tauri / pywebview / Electron) is a Phase-3 decision, deliberately unmade now.
- **Build order note:** the GUI is essential to the *mission* (ordinary users) but low *risk*, so it
  comes after the novel/risky parts (agent control + local generation) are proven headlessly.

### 5.5 MCP server: **official Python MCP SDK** — DECIDED
- Thin adapter that exposes core operations as MCP tools. Long operations return a job ID; a companion
  status tool reports progress; results auto-import into the media store on completion.

### 5.6 License: **Apache-2.0**, GPL engines at arms length — DECIDED
- Apache-2.0 = permissive + explicit patent grant → maximal adoption and corporate-safe contribution.
- FFmpeg (GPL full build) and MLT (LGPL/GPL) are invoked as **separate processes / at arms length**,
  never statically linked, so their copyleft does not propagate into Opmiere's own code. libopenshot
  (LGPL-3) is acceptable to link. ComfyUI runs as a separate process.

### 5.7 VRAM-adaptive generation — the local-quality bet — DECIDED (direction)

The core wager: **a modest GPU should reach high quality by spending *time*, not *money*.** The
techniques to run big models on small VRAM are known in the ComfyUI community but require expert
hand-assembly of node graphs — precisely the friction ordinary users cannot cross. Opmiere's value-add
is to **abstract that dark art into automatic, VRAM-aware generation profiles.** The techniques it
orchestrates:

**A. Quantize the weights** (shrink the model — the diffusion analogue of LLM quantization):
- **GGUF** (Q8 → Q2) via ComfyUI-GGUF; Flux / SD3 / Wan / Hunyuan all have GGUF builds.
- **FP8 (e4m3fn)** weight storage — saves memory even on Ampere (RTX 3070), where compute upcasts.
- **SVDQuant / NF4** 4-bit — near-FP16 quality at 4-bit; SVDQuant (Nunchaku) can be *faster*, not just smaller.

**B. Offload** (use the 32 GB of system RAM as overflow):
- **CPU / sequential offload** — keep only the active submodule resident in VRAM.
- **Block swapping** — stream transformer blocks VRAM↔RAM during the forward pass; the knob that lets
  13–14B video models run on 8 GB. `#blocks swapped` is a direct time-vs-VRAM dial.
- **Tiled VAE decode** — removes the decode-time VRAM spike that OOMs long / high-res video.

**C. Cheaper compute**:
- **Memory-efficient attention** (xFormers, SageAttention INT8) — less VRAM, faster.
- **Step-distilled / Turbo / LCM / Lightning** models — 4–8 steps vs 30–50 → far less wall-clock and
  lower sustained VRAM.

**D. Staged quality (draft → finish)** — maps perfectly onto the agent loop:
- Generate a fast low-res / low-step **draft**; the agent or user approves; only the *committed* shot
  is re-run at full quality or **upscaled** (tiled, dedicated video upscaler). The weak card pays the
  full cost only on shots that survive — cheap iteration, expensive commit.

**The product layer** (the actual differentiator — the techniques above are community-known):
1. On first run, detect **GPU + VRAM + system RAM**.
2. Define **generation profiles** (`8GB/quality-max-slow`, `8GB/balanced`, `24GB/fast`, …) that
   pre-bake the right combination of the above into ComfyUI workflow templates.
3. Expose a single **`quality: draft | balanced | max`** dial to the user *and the agent*. The user
   picks *what* and *how patient*; Opmiere picks *how* to make the card do it — no node-graph assembly.

> Honest caveat: the exact model + quant choices per profile are **validated empirically on the
> reference RTX 3070 at P2** — real benchmarks beat spec-sheet guesses, and this space moves monthly.
> What is decided *now* is the architecture (auto profiles + draft/finish staging + a quality dial);
> the *contents* of each profile are tuned during P2.

### 5.8 Deterministic effects & tools — editor-first, generation-additive — DECIDED

**Principle:** final quality must *not* rest solely on generative models. Most of what reads as
"professional" is achieved by **deterministic tools** that are instant, perfect, and free — no GPU
generation involved. Opmiere is a real editor first; generation is additive. This means it is useful
on day one, useful on machines with no capable GPU, and it lets an **agent do reliable deterministic
work with tools instead of gambling on generation for everything** — reserving expensive generation
for genuinely-new imagery only. This is the smarter, cheaper agent workflow.

Curated high-impact set (Premiere-like, *not* exhaustive — chosen by impact-per-effort):
- **Editing:** cut / trim / ripple / roll / slip, split, speed & time-remap (slow-mo, ramps).
- **Transitions:** cross-dissolve, dip-to-black/white, wipes.
- **Color:** curves, LUT/3D-LUT, white balance, saturation/contrast — carries most of the "pro look".
- **Transform:** crop, scale, position, rotate, Ken-Burns pan/zoom; (stabilization — later).
- **Keying/masking:** chroma key (green screen), luma key, shape masks.
- **Text:** titles, lower-thirds, captions/subtitles.
- **Stylize:** blur, sharpen, vignette, glow, film grain.
- **Audio:** gain, EQ, compression, ducking, noise reduction, fades.

Two facts make this cheap to deliver:
1. It **slots into the existing abstractions** — each is a clip `effect` + an `apply_effect` operation;
   the agent gets the exact same tools over MCP as the human.
2. The **FFmpeg-first render backend already provides most of it** (`curves`, `lut3d`, `chromakey`,
   `xfade`, `drawtext`, `zoompan`, `eq`, `acompressor`, `afade`, `arnndn` denoise, …) with zero new
   dependencies. Real-time interactive versions arrive with the P3 preview backend (GPU shaders /
   frei0r / movit). Advanced keying, motion tracking, and stabilization are explicitly **later**.

### 5.9 Local audio generation — speech / SFX / music — DECIDED (direction)

Not just image and video — audio is a first-class generation `kind`, same `GenerationProvider`
interface, same VRAM-adaptive quantization treatment (§5.7). All local-first, cloud-optional.
- **Speech / TTS:** Kokoro (small, strong, 8 GB-friendly), XTTS-v2 / F5-TTS (**voice cloning**), Piper
  (ultra-light). Voice cloning directly serves an existing need — narration in *the user's own voice*,
  not a canned preset, kept entirely local (no voice uploaded to the cloud).
- **Music:** MusicGen, Stable Audio Open — local, fine for short cues.
- **SFX:** Stable Audio Open / AudioGen — clips are short, so 8 GB copes well.

Honest tiering (consistent with §2): local TTS is near-cloud quality; local music is good-not-top-tier;
local SFX is fine. Cloud (ElevenLabs, Suno) remains the pluggable top-tier option. Some of this can run
*through* the existing ComfyUI provider (it has audio nodes); the rest via thin local model wrappers —
either way it is "another provider / kind", not new architecture.

### 5.10 Compositional generation & the agent-director loop — the north-star workflow

This is the *why* behind every abstraction above (§1 north star). The product is not a generator with a
timeline bolted on; it is a **director's toolkit** where a frontier LLM agent assembles a film from many
controlled fragments. The agent's real intelligence is not "stringing clips" — it is **maintaining
continuity** and **judging its own output**.

**Cross-fragment consistency (the hard problem).** Independently generated shots drift in character,
style, and lighting. The agent must actively counter this, and the framework must expose the levers:
- **Seed reuse**, **reference images (IP-Adapter)**, **LoRAs** for stable character/style.
- **ControlNet** (pose / depth / edge) to pin composition.
- **Frame chaining** for video continuity — generate shot B conditioned on shot A's last frame
  (first-frame / last-frame conditioning), so motion and look carry across the cut.
- **Deterministic color-match / grade** (§5.8) to harmonize fragments after the fact.
These are exposed as generation `params` and `apply_effect` tools so the agent *plans for* consistency
rather than firing blind, independent generations.

**The agent needs eyes (feedback loop).** Compositional direction requires the agent to *see* what it
made and decide keep / regenerate / adjust. The framework therefore supports an **inspect loop**: the
core can render a frame, thumbnail strip, or short preview of any clip/range and hand it back to a
**multimodal** agent for critique. Generate → render preview → inspect → decide → iterate. (This reuses
the same media-understanding capability as P4 semantic search, but its primary purpose is quality
control, not indexing.)

**Model-agnostic orchestration.** The director is whatever frontier agent is strongest — Claude
(Opus 4.8), GPT-5.5, future models — reached through **MCP**, never hard-wired. Opmiere supplies the
hands and feet; the user brings the brain.

**Why the assembled result can beat one-shot.** Length is unbounded; every cut, transition, grade, and
audio layer is deliberate; continuity is managed; and the expensive generation budget is spent only on
fragments that survive the agent's own critique (draft→finish, §5.7 D). Craft + control + audio, stacked
by a capable director, exceed what a single uncontrolled generation — even from a larger model — returns.

---

## 6. The project model (the crown jewel)

Agent-legibility drives the schema. Time is in **frames over an explicit timebase**, never bare
seconds. Everything has a stable, addressable **id**.

```jsonc
// .opm bundle → project.json  (sketch, not final)
{
  "schema": 1,
  "id": "prj_a1b2",
  "timebase": { "fps": 30, "sample_rate": 48000 },
  "resolution": { "w": 1920, "h": 1080 },
  "media": [
    { "id": "med_01", "kind": "video", "path": "media/clip1.mp4",
      "duration_frames": 900, "has_audio": true },
    { "id": "med_02", "kind": "image", "path": "media/gen_sunrise.png",
      "origin": { "provider": "comfyui", "job": "job_77", "prompt": "sunrise over sea" } }
  ],
  "tracks": [
    { "id": "trk_v1", "kind": "video", "clips": [
        { "id": "clp_01", "media": "med_01", "start": 0,
          "in": 30, "out": 330, "effects": [] }
    ]},
    { "id": "trk_a1", "kind": "audio", "clips": [ /* … */ ] }
  ]
}
```

- `start` = timeline position (frames). `in`/`out` = source trim (frames). Explicit and unambiguous
  for both a renderer and an LLM.
- Generated assets carry an `origin` (provider, job, prompt) so the agent can reason about *how* a clip
  came to exist and regenerate it.

---

## 7. The operation API (single mutation surface)

Every edit — from the GUI, from an agent, from undo/redo — is an **Operation** object. This is the one
choke point where state changes, which gives us free undo/redo, event emission (so all clients stay in
sync), and a 1:1 mapping to MCP tools.

Representative operations (names indicative):

```
import_media(path)                       → med_id
add_clip(track, media, start, in, out)   → clp_id
move_clip(clip, new_start)
trim_clip(clip, in, out)
split_clip(clip, at_frame)               → (clp_id, clp_id)
delete_clip(clip)
add_track(kind)                          → trk_id
apply_effect(clip, effect, params)
generate(kind, prompt, provider, params) → job_id      # async
place_generated(job, track, start)                        # after job done
export(path, preset)                     → job_id      # async
```

MCP tools are a near-mechanical projection of this list. The GUI calls the exact same functions.

---

## 8. Async generation / render job model

```
agent/GUI ─ generate(...) ─►  JobManager  ─►  provider (ComfyUI | cloud)
                                  │
        job_id ◄──────────────────┘   (returns immediately)

agent/GUI ─ job_status(job_id) ─► {queued|running|done|error, progress, result_media_id?}
                                  on done → asset auto-imported into media store
```

- One model for local and cloud; the agent polls or subscribes to events.
- Failures are first-class (`error` + message), never a hang.

---

## 9. Roadmap (build order = risk order, not mission order)

| Phase | Goal | Proves |
|-------|------|--------|
| **P0 Foundation** | Project model + `.opm` bundle + FFmpeg render backend. Import → place → trim/cut → export, headless. | The engine path works on Windows. |
| **P1 Agent control + core tools** | Operation API + MCP server. Claude Code builds/edits a timeline and exports it, no GUI. Includes the cheap **deterministic tools** (§5.8) FFmpeg already gives: transitions, color, text, audio basics. | Core differentiator + editor-first, front-loaded. |
| **P2 Generation (incl. audio)** | `GenerationProvider` + ComfyUI local (image → LTX-Video) + **audio: TTS / SFX / music** (§5.9) + one cloud provider, all VRAM-adaptive (§5.7). Agent: "generate X → place on timeline." | Local-first + cloud-optional thesis, across media types. |
| **P3 GUI** | Web frontend: timeline, preview player, media bin, generation panel, agent chat. Interactive render backend for scrubbing + real-time effects. | Ordinary-user usability. |
| **P4 Depth** | *Advanced* effects (keying, motion tracking, stabilization), semantic media search, packaging/installer, docs, OSS release hygiene. | Ready for the world. |

Note: **basic deterministic effects land early (P1)** because FFmpeg makes them nearly free; only the
*advanced* effects wait for P4. This keeps "it's a real editor" true from the first agent-drivable build.

**P2 status:** P0, P1, and P1's full deterministic-tools line (color, fade, gain, text, cross-dissolve
transitions, **plus speed/time-remap** — `Clip.speed` + `timeline_duration_frames`, kept separate from
`duration_frames` so source-frame math stays untouched; video via `setpts`, audio via `atempo`
(0.5-2.0, ffmpeg's real single-filter limit, enforced at render time)) are done.

**P2.1 (image), P2.2 (video), and P2.3 (speech + voice cloning) are all proven end to end**:
`GenerationProvider` interface + a local `ComfyUIProvider` wired through Editor's async job model
(`generate` → poll `job_status` → `place_generated`) and exposed as MCP tools — a real MCP client can
ask for an image, a short video, or spoken narration (preset voice or cloned from a reference clip),
place it on the timeline, and export a real video containing it, over the same stdio path Claude
Desktop/Cursor use. Video runs on the original LTX-Video 2B line (distilled, fp8), not the newer
LTX-2/2.3 flagship (19-22B params, 16 GB+ even quantized — verified too heavy for this 8 GB card before
committing to a download; the "LTX-Video" name now spans two very different model generations, worth
knowing before reaching for it again). Speech runs on Qwen3-TTS (Apache-2.0 — chosen specifically over
XTTS-v2/F5-TTS, both non-commercial-licensed). Real numbers on the reference RTX 3070: image ~7s/~2GB
VRAM, video (512x320, 65 frames/25fps, 30 steps) ~22s/~6.4GB VRAM peak — both comfortably inside the
8 GB budget without needing any of section 5.7's offload/quantization techniques yet. Still open within
P2: SFX/music (§5.9), a cloud provider, and the VRAM-adaptive quantization *profiles* from §5.7
(everything above runs at whatever precision its checkpoint ships in — the auto-selecting-by-detected-
VRAM machinery, and pushing a *bigger* model than currently fits via GGUF/block-swap, is not yet built).

The P0→P2 headless demo — *"Claude, cut the dead air, generate a 5-second sunrise B-roll, add a
voiceover in my own cloned voice, cross-dissolve between shots, color-grade warm, and export a 1080p
cut"* — mixes generation *and* deterministic tools, and de-risks the entire vision before a single
pixel of GUI exists.

---

## 10. Open decisions (deliberately unmade)

- Interactive render backend: **libopenshot vs MLT** — decide when P3 starts, against real preview needs.
- Cloud aggregator: **Replicate vs fal.ai** — decide when P2 starts, against model coverage + pricing.
- Desktop shell: **Tauri vs pywebview vs Electron** — decide when P3 starts, against packaging weight.
- These are recorded as open on purpose; committing early would be guessing.
