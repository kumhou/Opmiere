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

**Generated-model licenses are a different axis, tracked not avoided.** JH's explicit call: pick
*generation* models for quality first; a non-commercial-licensed checkpoint (e.g. Flux.1-dev) is fine to
use, but every job must record which checkpoint made it and that checkpoint's real commercial-use terms,
so a project can be audited before it's sold/published rather than the restriction being silently lost.
Implementation (`opmiere.generation`): a `CHECKPOINT_LICENSES` registry in `ComfyUIProvider` maps each
checkpoint filename/repo id → a `ModelLicense` (name, `commercial_use: yes|no|conditional`, notes),
verified against each model's actual license text (never assumed from reputation — caught real
surprises this way, e.g. LTX-Video's license is conditional on company ARR, not a flat yes/no). This
flows `GenerationJob.license` → `Media.origin["license"]` at `place_generated()` time, and
`Editor.get_license_report()` (also an MCP tool) audits a whole project's placed media at once. **This
is metadata only** — it is never watermarked or otherwise mixed into the generated pixels/audio
themselves; nothing about the output content changes based on license.

### 5.7 VRAM-adaptive generation — the local-quality bet — DECIDED, profiles system IMPLEMENTED

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
- **The "upscaled" half is implemented for images** (§9): `generate(kind="upscale")` runs a
  deterministic ESRGAN pass over an approved draft — no sampling/seed/steps, so it's cheap relative to
  a full re-generate at a higher tier. Video upscale remains open — no single ComfyUI node covers it the
  way `ImageUpscaleWithModel` does for images; would need frame-extract + upscale + reassemble.

**The product layer** (the actual differentiator — the techniques above are community-known):
1. On first run, detect **GPU + VRAM + system RAM**.
2. Define **generation profiles** (`8GB/quality-max-slow`, `8GB/balanced`, `24GB/fast`, …) that
   pre-bake the right combination of the above into ComfyUI workflow templates.
3. Expose a single **`quality: draft | balanced | max`** dial to the user *and the agent*. The user
   picks *what* and *how patient*; Opmiere picks *how* to make the card do it — no node-graph assembly.

**Implemented in `opmiere.generation.profiles`** (P2, this session): a real `GENERATION_PROFILES` table
and `recommend(kind, vram_gb, offload) -> GenerationProfile` function, exposed as the
`recommend_generation_profile` MCP tool + `ComfyUIProvider.recommend_profile()`. JH's structural ask —
split by **offload vs. non-offload as two tracks**, not one "best pick per tier" table — is exactly how
selection works: `offload=False` returns the highest tier that fits detected VRAM outright (via
`ComfyUIProvider.detect_vram_gb()`, reading ComfyUI's own `/system_stats` — ~8.0GB detected on the
reference RTX 3070, matching spec); `offload=True` returns the best profile in the offload track
regardless of fit, since that track's whole point is not needing to fit. Every number in the table is a
real measurement from this session (§9), not a spec-sheet guess — this also directly answers the
"validate empirically" caveat this section used to carry: image has 3 tiers (sd1.5 draft → flux-schnell
balanced → flux-dev max, all non-offload), video has 2 non-offload tiers (ltx-video draft → wan2.1
balanced) plus 1 offload tier (wan2.2-moe max), speech has 1 tier so far (qwen3-tts). One real fix worth
recording: the first version of `recommend()` applied a 10% VRAM safety margin on top of each measured
peak, which wrongly excluded wan2.1 (7.7GB peak) on the exact 8.0GB card it was proven to run on —
removed, since each `vram_gb` is already an absolute observed peak, not a theoretical minimum;
stacking a margin on top just double-counts caution against JH's explicit "tight fit is fine, quality
is what matters" stance. Re-benchmarking on other hardware (the 1660 Super, once installed; any other
card a user runs this on) is real follow-up work — the *mechanism* generalizes, the *table contents*
don't until measured there too.

### 5.8 Deterministic effects & tools — editor-first, generation-additive — DECIDED

**Principle:** final quality must *not* rest solely on generative models. Most of what reads as
"professional" is achieved by **deterministic tools** that are instant, perfect, and free — no GPU
generation involved. Opmiere is a real editor first; generation is additive. This means it is useful
on day one, useful on machines with no capable GPU, and it lets an **agent do reliable deterministic
work with tools instead of gambling on generation for everything** — reserving expensive generation
for genuinely-new imagery only. This is the smarter, cheaper agent workflow.

Curated high-impact set (Premiere-like, *not* exhaustive — chosen by impact-per-effort):
- **Editing:** cut / trim / ripple / roll / slip, split, speed & time-remap (slow-mo, ramps).
- **Transitions:** cross-dissolve, dip-to-black/white, wipes — **all done** (§9), via ffmpeg xfade's
  own transition vocabulary (`_XFADE_TRANSITION_BY_TYPE`), not a separate implementation per style.
- **Color:** curves, LUT/3D-LUT, white balance, saturation/contrast — carries most of the "pro look".
- **Transform:** crop, scale, position, rotate, Ken-Burns pan/zoom; (stabilization — later).
- **Keying/masking:** chroma key (green screen), luma key, shape masks.
- **Text:** titles, lower-thirds, captions/subtitles.
- **Stylize:** blur, sharpen, vignette, film grain **done**; glow still open (needs a multi-stage
  blur+screen-blend filtergraph, not a single filter like the rest here).
- **Audio:** gain, compression, noise reduction, fades, EQ **done**; ducking **done** too, as the
  track-level relationship it always needed to be (`Track.duck` + `set_ducking`, compiled to a
  sidechain keyed by a second track - see the audio-subsystem writeup below).

Two facts make this cheap to deliver:
1. It **slots into the existing abstractions** — each is a clip `effect` + an `apply_effect` operation;
   the agent gets the exact same tools over MCP as the human.
2. The **FFmpeg-first render backend already provides most of it** (`curves`, `lut3d`, `chromakey`,
   `xfade`, `drawtext`, `zoompan`, `eq`, `acompressor`, `afade`, `arnndn` denoise, …) with zero new
   dependencies. Real-time interactive versions arrive with the P3 preview backend (GPU shaders /
   frei0r / movit). Advanced keying, motion tracking, and stabilization are explicitly **later**.

### 5.9 Local audio generation — speech / SFX / music — speech + music IMPLEMENTED, SFX open

Not just image and video — audio is a first-class generation `kind`, same `GenerationProvider`
interface, same VRAM-adaptive quantization treatment (§5.7). All local-first, cloud-optional.
- **Speech / TTS — done (P2.3):** Qwen3-TTS (Apache-2.0, preset voices + reference-clip cloning).
- **Music — done:** **ACE-Step** (Apache-2.0, ComfyUI-bundled all-in-one 3.5B checkpoint), not the
  originally-speculated MusicGen/Stable Audio Open — Stable Audio Open turned out to be gated + a
  custom "other" license (checked via the HF API, not assumed) needing an auth token this session
  didn't set up, while ACE-Step is clean and ungated. `generate(kind="music")`: prompt is the *tags*
  description (comma-separated genre/mood/instrument descriptors, ACE-Step's own vocabulary, not a
  sentence); `lyrics` defaults to `"[instrumental]"` for background-score use (the common case for a
  video editor), or pass real `[verse]`/`[chorus]` lyrics for a sung track. Real result on the RTX
  3070: 30s of audio, 50 steps, **~24s generation, ~7.5GB VRAM peak** — comfortably non-offload.
  Verified as real audio (not silence/noise) via volume analysis (mean -16.8dB) and a waveform plot
  showing real musical dynamics + a natural fade-out, since generated audio can't be "eyeballed" the
  way a frame can.
- **SFX — still open:** Stable Audio Open's own general text-to-audio capability (not just music) is
  the natural fit, but its gating means the download needs an HF account + accepted-terms auth token,
  unlike every other model this project has pulled so far (all anonymous/ungated). Deferred until that
  auth flow is worth setting up, not for a technical reason.

Honest tiering (consistent with §2): local TTS is near-cloud quality; local music (ACE-Step) is
good-not-top-tier but real and fast. Cloud (ElevenLabs, Suno) remains the pluggable top-tier option.
Both implemented kinds run *through* the existing ComfyUI provider (it has native audio nodes) — no new
architecture, exactly as predicted: "another provider / kind."

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

**Free gate before the agent's eyes get involved — IMPLEMENTED.** JH's explicit worry: a full inspect
loop that sends every generated fragment to a multimodal agent burns tokens fast. Most outright failures
(a generation that's just a static frame, silence where narration should be, solid black, out of focus)
are catchable with zero model calls. `render.quality_check` runs ffmpeg's own `blackdetect`/
`freezedetect`/`blurdetect`/`silencedetect` filters (real thresholds, verified against actual sharp vs.
blurred output, not guessed) and returns `passed`/`issues` - exposed as the `quality_check` MCP tool.
Call it on a job's `result_path` before `place_generated` ever commits a broken generation to the
timeline. This is the first, cheapest stage of the funnel below; the agent's actual attention is reserved
for what this can't catch (composition, subject fidelity, style match).

**The agent's eyes (feedback loop) — contact sheets IMPLEMENTED, full inspect loop still open.**
Compositional direction requires the agent to *see* what it made and decide keep / regenerate / adjust,
for judgments quality_check can't make (composition, subject fidelity, does the motion look right).
`render.make_contact_sheet` tiles cols*rows evenly-spaced thumbnails from a clip into one small grid
image (`make_contact_sheet` MCP tool) - a shot's whole motion arc in one small image the agent reads,
instead of many full-res frames. Verified on a real generated clip (Wan2.1's paper-boat video): the tiled
frames show the boat's drift and water reflections changing coherently across the grid, exactly the
"does this look like continuous motion" signal the agent needs, at a fraction of the token cost of
several large frames. Generate → quality_check (free) → make_contact_sheet → agent inspects → decide →
iterate. The draft→finish half (§5.7 D) now has its missing tool too: `generate(kind="upscale")` turns
an approved draft straight into a finished asset without a full re-generate. Deliberately **not** wrapped
in a new combined "accept/regenerate" method — that would either force `make_contact_sheet` to run right
after `quality_check` every time (defeating the free-gate-before-expensive-step staging this section
argued for) or duplicate what `generate`/`place_generated` already do. The decision itself stays agent
policy over existing tools: quality_check fails → regenerate; passes but composition/fidelity is off on
the contact sheet → regenerate (optionally with a higher-tier `model`, same `seed`, for continuity) or
adjust params; looks right → `generate(kind="upscale", params={"source_path": ...})` (cheap) or a
higher-tier regenerate (expensive) → place_generated. What's genuinely still open is *encoding* that
policy somewhere an agent reliably follows it (an MCP tool description, a skill/system-prompt), not a
missing capability. (Contact sheets reuse the same media-understanding
capability as P4 semantic search, but their primary purpose here is quality control, not indexing.)

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

**Multi-track video** landed too, ahead of schedule: the render backend now composites N video tracks
(first = base/background, later ones = full-frame overlay layers active only during their own clips'
windows via ffmpeg's `overlay` + `enable`), unblocking anything that needs a second visual layer. Editor
and the model never needed changes — they never restricted track counts, only `render/ffmpeg.py` did.
**Chroma key is now built too**: a new `chroma_key` effect (`color`/`similarity`/`blend`, ffmpeg's own
`chromakey` filter) on any clip. The real gotcha, caught with a spike script before touching production
code: the alpha `chromakey` produces gets silently killed by the existing `pad=...:color=black` step
(opaque padding) unless a chroma-keyed clip's chain switches to `pad=...:color=black@0.0` + an explicit
`format=yuva420p` — otherwise it either errors or, worse, renders opaque black bars. The `overlay` step
itself needed no change; it already respects incoming alpha with no `format=` option. Verified with a
real render (blue background + green screen "subject" clip), sampling actual output pixels (blue
showing through, red subject intact) rather than just "no ffmpeg error."

**`luma_key` and `curves` are built too** — `luma_key` reuses chroma_key's alpha-survival handling
(`_video_clip_chain`'s `has_alpha` check now covers both), verified with the same real-pixel-sampling
render (white background keyed transparent, black subject box intact). `curves` wraps ffmpeg's own
`preset` vocabulary (vintage, cross_process, negative, …) for one-shot full-frame color grading.

**`crop` and `rotate` are built too** — plain per-clip transforms (ffmpeg's own `crop`/`rotate` filters),
verified the same way (a red/blue split-color clip cropped to exactly the red half; a rotated frame's
corners correctly filled). Deliberately narrower than the full "transform" idea in §5.8's curated list:
scaling/positioning a clip smaller than the canvas (for PiP) needs the overlay compositing step itself to
take a configurable position instead of always `x=0:y=0` full-frame — a real architecture change, not
just another filter fragment — so that's its own not-yet-built item (see §10/roadmap), not folded in here.

**PiP position/scale is now built** — the item flagged above. `Clip.position` (`{"x", "y", "scale"}`,
`None` = full-frame, unchanged default) is a clip-level field like `transition_in`/`speed`, not an
`effects` entry, since it changes the overlay compositing step itself rather than one clip's own pixel
chain. `Editor.set_position(clip_id, x, y, scale)`/`clear_position` (MCP tools of the same names): `scale`
(0,1] is the box size as a fraction of the canvas, aspect preserved via the same fit-then-pad approach
full-frame clips already use; `x`/`y` (each [0,1]) place the box's top-left corner as a fraction of the
*room it has to move in* (canvas minus box size) so the whole box always stays on-canvas by construction
— e.g. `x=1,y=1,scale=0.25` is a quarter-size box flush in the bottom-right corner. Only takes visual
effect on an overlay video track (any track after the first); the base track keeps rendering full-frame,
`_video_clip_chain` now takes the target box size as a parameter instead of always the canvas size, so
overlay clips scale/pad to their own smaller box before the `overlay=x=..:y=..` step places it. Real bug
caught and fixed before landing: an odd box dimension (e.g. `scale=0.5` on a 90px-tall canvas → 45)
broke ffmpeg's pad/encode with an opaque "Padded dimensions cannot be smaller than input dimensions"
error — yuv420p's chroma subsampling needs even width/height, so box dimensions are now rounded down to
even. Verified with a real render (blue base + a red overlay pinned bottom-right at half size): the box
lands exactly where requested, blue everywhere outside it, red only inside.

**Image upscale is now built too** — `generate(kind="upscale")`, the "or upscaled" half of §5.7 D's
draft→finish staged-quality idea (§5.10 also updated). A new `ComfyUIProvider._build_upscale_workflow`
wraps ComfyUI's core `UpscaleModelLoader`/`ImageUpscaleWithModel` nodes around a fresh checkpoint,
**RealESRGAN_x4plus** (BSD-3-Clause, verified via GitHub's repo-license API — commercial-safe, no
restrictions), downloaded this session (67MB, official `xinntao/Real-ESRGAN` v0.1.0 release asset). No
sampler/seed/steps/cfg — a fixed super-resolution pass, not a diffusion job — so it's stable and, real
numbers on this RTX 3070: **256×256 → 1024×1024 (exactly 4x) in 1.3s, ~2.6GB VRAM peak** (most of that
the ~1.5GB OS/desktop baseline every measurement here already nets out against elsewhere), dramatically
cheaper than any full regenerate (compare flux-dev 82s/7GB, wan2.1 139s/7.7GB, wan2.2-moe 283s/17.5GB
combined). Verified end to end against the live server (not mocked): real dimension check plus pixel-
extrema sampling on both the draft and the upscaled result (full 0–255 range on every channel, so
neither is a blank/flat placeholder). Reuses the source_path-upload pattern speech's `reference_audio`
established (copy into ComfyUI's own `input/` folder first) rather than inventing a new upload path.
Deliberately scoped to images only — video upscale has no equivalent single ComfyUI node and stays open
(§5.7 D). Slots into the *existing* async job model unchanged: `generate(kind="upscale", params=
{"source_path": ...})` → poll `job_status` → `place_generated` — no new Editor method, since an upscale
is, mechanically, just another generation job whose "prompt" happens to be an image instead of text (see
§5.10 for why this deliberately isn't wrapped in a new combined accept/regenerate abstraction).

**§5.8's curated effects/transitions list is now substantially closed out.** Three independent additions,
each slotting into an existing mechanism rather than a new one:
- **Transitions:** `KNOWN_TRANSITION_TYPES` grew from just `cross_dissolve` to `dip_to_black`,
  `dip_to_white`, `wipe_left/right/up/down` - all free, since the render side was already parameterizing
  ffmpeg's own `xfade` filter (`_XFADE_TRANSITION_BY_TYPE` maps each Opmiere name to one of xfade's real
  57 transition values, verified via `ffmpeg -h filter=xfade`, not guessed) - previously hardcoded to
  `transition=fade`. `add_transition`/`remove_transition`/the overlap-shrinks-the-timeline math needed no
  changes at all. Verified with real pixel sampling on a red-clip→green-clip cut, sampling left/right
  quarter-frame pixels mid-transition: `cross_dissolve` gave an identical muddy blend on both sides
  (126,62,0 both), `dip_to_black` gave identical near-black on both sides (0,30,0 both), `wipe_left` gave
  *different* values per side (pure red vs. green-dominant) - proof the three genuinely render distinct
  transition types, not all silently falling back to one.
- **Stylize:** `sharpen` (ffmpeg `unsharp`, one knob: `amount` → `luma_amount`) and `film_grain` (ffmpeg
  `noise`, one knob: `amount` → `alls`, fixed `allf=t+u` for temporal+uniform grain rather than a static
  dead-pixel pattern). Verified real, not a no-op: sharpen roughly doubled a crude edge-energy proxy
  (sum of horizontal adjacent-pixel deltas) on real footage (96471 → 224361); film_grain took a
  perfectly static flat-color source (frame-to-frame diff = 0, confirmed) to a frame-to-frame diff of
  208263 - real per-frame noise, not a single baked-in pattern. Glow stays open - needs a multi-stage
  blur+screen-blend filtergraph, not a single filter like every other stylize effect landed so far.
- **Audio:** `compression` (ffmpeg `acompressor` - `threshold_db`/`ratio`/`attack_ms`/`release_ms`/
  `makeup_db`; confirmed empirically that `threshold`/`makeup` accept a `dB` suffix same as the existing
  `gain` effect's own `db` field, so the effect's public API stays dB-only rather than mixing linear and
  dB knobs) and `noise_reduction` (ffmpeg `afftdn`, one knob: `amount` → `nr`, dB of reduction). Verified
  real: on a loud-clip/quiet-clip pair (30dB apart), aggressive compression (ratio 20, threshold -40dB)
  narrowed the gap to 9.9dB; on a sine tone mixed with real injected white noise (`anoisesrc`),
  `noise_reduction` measurably dropped RMS energy (-24.90dB → -25.14dB - a small honest delta, since
  afftdn targets the noise floor under a signal rather than the signal itself, not a red flag). Ducking
  landed later as part of the audio subsystem (next writeup below) - it needed a sidechain keyed by a
  second track, which made it a track-level piece (like multi-track compositing was), not a per-clip
  effect.

**Audio EQ landed too**: a new `audio_eq` effect (ffmpeg's `equalizer`, one peaking band -
`frequency_hz`/`gain_db`/`q`) - named `audio_eq` rather than the shorter `eq` specifically because the
existing `color` effect already uses ffmpeg's own *different*, unrelated `eq` filter (video brightness/
contrast/saturation); reusing the name on an agent-facing surface would invite exactly the kind of
same-name-different-thing confusion this project's license/model-name mixups (§5.6, §9) already show is
a real failure mode, not a hypothetical one. Multi-band EQ needed no new mechanism: apply_effect this at
several `frequency_hz` values and they stack, same as every other effect already does. Verified real: a
1000Hz test tone with a band centered on 1000Hz measured **+17.2dB at a +18dB boost setting and exactly
-18.0dB at a -18dB cut setting** (volumedetect mean_volume, before/after) - close to 1:1 because the tone
sits exactly on the band's own center frequency, the case where a peaking filter's effect is most direct.

**The audio subsystem proper landed as one coherent piece** - multi-track mixing, ducking, and the
agent's "ears" - closing out the last "later work" markers on the audio side:

- **Multi-track audio mixing** reuses the base/overlay convention video tracks already established,
  deliberately (one mental model, not two): the first audio track is the base (contiguous from frame 0,
  hard cuts or declared transitions), every later one is an overlay allowed gaps - a music bed on the
  base, voiceover lines dropped at any frame on a second track, SFX on a third. Overlay clips are
  positioned with `adelay` and summed with `amix normalize=0` - normalize=0 because amix's default 1/N
  re-scaling would silently re-balance the whole mix every time a track is added, exactly the kind of
  invisible mutation an agent can't reason about; levels stay as authored, balanced explicitly via the
  `gain` effect. Every audio clip chain now ends in an explicit `aformat` (float/stereo) so a mono
  voiceover meeting a stereo bed inside concat/acrossfade/amix/sidechaincompress is a non-event rather
  than a format-negotiation surprise.
- **Ducking** (`set_ducking`/`clear_ducking`, stored as `Track.duck`) is a *track-level relationship*,
  as §5.8 predicted: `sidechaincompress` on the ducked track's submix, keyed by an `asplit` copy of the
  key track's **pre-duck** submix - pre-duck keys make mutual ducking acyclic by construction, no cycle
  detection needed. Two empirical findings are baked into the compiled graph: `threshold`/`makeup`
  accept the same `dB` suffix acompressor does (API stays dB-only), and sidechaincompress ends at its
  *shortest* input - an unpadded 1s key truncated a 4s main to 1s in testing - so every key is `apad`ed
  with silence (which is also the right semantics: no key signal = no ducking), with the main input
  still bounding output length. `delete_track` clears any other track's duck-against reference to the
  deleted track rather than leaving every later export to fail on a dangling id.
- **`analyze_audio` - the ears to `make_contact_sheet`'s eyes** (§5.10). Direct answer to JH's dogfood
  question ("你有什么办法直接拥有'耳朵'来辨别吗？就跟你的眼睛一样"): deterministic ffmpeg metering -
  volumedetect mean/max, ebur128 integrated LUFS / loudness range / true peak, silencedetect regions -
  plus an optional waveform-over-spectrogram PNG (`showwavespic`/`showspectrumpic`/`vstack`), because
  the numbers say "how loud" but the picture says *where* and *what*. Free and local, so it runs before
  any generated audio earns a place on the timeline and again on the export to verify the mix - e.g.
  that ducking measurably made room for the voiceover.
- **`place_from_file`** rounds out the placement paths: import + place as one operation (and one undo),
  the local-file twin of `place_generated`, with the same omit-duration-to-use-real-duration rule that
  place_generated already learned the hard way.

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
8 GB budget without needing any of section 5.7's offload/quantization techniques yet.

**First real §5.7 quantization result: dramatic, not marginal.** Flux.1-schnell at GGUF Q4_K_S (the
first quantized model wired in) produces photorealistic image quality far beyond SD1.5, still comfortably
inside 8 GB (~7GB VRAM peak, 1024x1024, 34s, 4 steps) — this alone justified making quantized GGUF
checkpoints a normal option, not just a fallback for oversized models. Flux.1-dev (same graph, 20 steps,
higher quality still, non-commercial license — see §5.6) is wired in alongside it as the quality-max
image option. `generate(kind="image")` now takes `model: sd1.5 | flux-schnell | flux-dev`. The
license-tracking mechanism (§5.6) shipped in the same pass, since flux-dev was the first checkpoint that
actually needed it.

**Video's quality-tier, non-offload option: Wan2.1 T2V 1.3B.** Same pattern as Flux for images —
`generate(kind="video")` now takes a `model` param, LTX-Video 2B staying the fast default. Real
side-by-side on this RTX 3070 (different prompts, so a qualitative not pixel-diff comparison, but the
gap is visually obvious): Wan2.1 renders noticeably sharper detail and more physically coherent lighting
than LTX-Video's softer, more motion-blurred output. The cost: ~139s vs LTX's ~22s (~6x slower) and a
tighter VRAM margin (~7.7GB peak vs ~6.4GB, both measured the same way - absolute `nvidia-smi` peak
including ~1.5GB OS/desktop baseline - so Wan2.1 leaves under 500MB of headroom on an 8GB card, still
technically non-offload but with much less margin than LTX-Video). License is Apache-2.0 (verified via
the HF API, not assumed) - strictly more permissive than LTX-Video's ARR-conditional terms.

**Video's offload-tier option, proven real: Wan2.2 T2V A14B (MoE).** This is the direct answer to JH's
"can offload actually get me a bigger/better model" question - and it works, with no special
configuration. Wan2.2's 14B model ships as two GGUF experts (HighNoise + LowNoise, ~8.75GB each, 17.5GB
combined - neither fits this 8GB card alongside the other, let alone both at once). Rather than building
any offload mechanism, the workflow just references both UnetLoaderGGUF checkpoints and lets ComfyUI's
own default model management page them in and out of VRAM as needed. Real `nvidia-smi` sampling during
a test run confirmed this happening automatically: usage oscillated between ~4GB and ~7.9GB rather than
climbing toward 17GB+, as the two experts were swapped in turn for their respective sampling stages
(standard two-stage `KSamplerAdvanced` hand-off, same pattern as an SDXL base/refiner pair). Cost: ~283s
for a small 480x480/17-frame test (vs Wan2.1's 139s for a larger 832x480/33-frame one) - slower, from
swap I/O plus a bigger active model per stage, exactly the tradeoff JH said was worth it. Quality was
the best of the three video options tested, visibly - more scene complexity and depth of field than
either LTX-Video or Wan2.1 produced. License: Apache-2.0 (verified via the HF API). `generate(kind=
"video")` now takes `model: ltx-video | wan2.1 | wan2.2-moe`.

**What this proves about JH's original research question** (no hardware upgrade, GPU cluster or RAM/
disk as VRAM overflow): the RAM-overflow half needed zero new code - ComfyUI's stock model manager
already does it whenever a workflow's combined model footprint exceeds VRAM. The GPU-cluster half (the
spare GTX 1660 Super, via e.g. ComfyUI-MultiGPU/DisTorch2) remains untested since the card isn't
physically installed - installing it was explicitly the last-resort option, not yet needed since
software-only paging already delivers a working offload tier.

**The auto-selecting-by-detected-VRAM *profiles* machinery from §5.7 is now built**, not just designed:
`opmiere.generation.profiles.recommend(kind, vram_gb, offload)` + the `recommend_generation_profile` MCP
tool, real-measurement-backed, split into non-offload/offload tracks exactly as JH asked (see §5.7 for
the full writeup, including a real bug caught and fixed: an initial safety margin wrongly excluded
wan2.1 on the exact card it was proven to work on).

**Music generation is also done (§5.9): ACE-Step**, Apache-2.0, `generate(kind="music")` - 30s
instrumental/song, ~24s generation, ~7.5GB VRAM peak, comfortably non-offload alongside every other
kind's default. Real audio verified via volume analysis + waveform plot (generated audio can't be
eyeballed like a frame), and confirmed it round-trips cleanly through Opmiere's own `probe()`/
`import_media` path, not just raw ComfyUI.

Still open within P2: SFX (§5.9 - blocked on Stable Audio Open's gating needing an HF auth token this
session didn't set up, not a technical blocker), a cloud provider, re-benchmarking the profiles table on
hardware other than the reference RTX 3070 (the spare GTX 1660 Super, once installed, would be the first
non-8GB data point), further offload-tier video candidates beyond wan2.2-moe (HunyuanVideo, the
LTX-2 flagship) if an even-higher ceiling is ever wanted, and video upscale (image upscale is done; video
needs frame-extract + upscale + reassemble, no single ComfyUI node covers it).

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
