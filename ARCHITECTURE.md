# Opmiere — Architecture

> **Open Premiere** — an open-source, agent-native non-linear video editor for Windows.
> Humans edit with a GUI; AI agents (Claude Code, Cursor, any MCP client) drive the *same*
> editing engine through a Model Context Protocol server. Generative AI (image / video / audio)
> runs **locally on your own GPU first**, with **paid cloud APIs as an optional quality boost**.

Status: **v0.1 — design.** Nothing here is frozen except where marked **DECIDED**. This document is
the single source of truth for *why* the system is shaped the way it is.

---

## 1. Why this exists

Existing open-source NLEs (Shotcut, Kdenlive, OpenShot, Olive) are excellent editors but have **no
agent interface** — you cannot tell an LLM "cut the dead air, generate a B-roll clip of a sunrise,
drop it at 0:12, and color-match it to the previous shot." Palmier Pro proved the agent-native NLE
concept but is **macOS-only, closed-source, and its generation is a paid subscription**.

Opmiere targets the gap:

1. **Agent-native.** Every edit a human can do, an agent can do, through one shared operation API.
2. **Local-first generation.** Generative AI runs on the user's own GPU (free) via ComfyUI; cloud
   APIs are pluggable providers for when quality matters and the user is willing to pay.
3. **Open source, Windows-first.** The audience is ordinary creators priced out of Runway/Sora/Kling
   subscriptions who have a gaming GPU sitting idle.

---

## 2. Hardware baseline (the constraint that shapes everything)

Primary dev/reference machine: **NVIDIA RTX 3070, 8 GB VRAM, 32 GB RAM, Windows 11.**

8 GB VRAM is the *entry tier* for generative AI, and it dictates the product design:

| Task | Local on 8 GB | Verdict |
|------|---------------|---------|
| Image gen (SDXL, SD1.5) | comfortable | ✅ primary local path |
| Image gen (Flux, 12B) | needs GGUF quant, slow | ⚠️ usable |
| Video gen — LTX-Video | designed for consumer GPUs | ✅ primary local video path |
| Video gen — CogVideoX-2B / Wan-1.3B | with CPU offload, slow, short/low-res | ⚠️ draft only |
| Video gen — Hunyuan, Wan-14B | does not fit | ❌ cloud only |

**Consequence (DECIDED):** local generation is positioned as *draft / previz / storyboard* tier;
final-quality video is expected to come from cloud providers. This is not a limitation to hide — it
*is* the product: cheap local iteration, pay only for the shots you commit to. The architecture
therefore treats local and cloud generation as **interchangeable providers behind one interface**,
never hard-wiring either.

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
| **P0 Foundation** | Project model + `.opm` bundle + FFmpeg render backend. Import → place clips → export a video, headless. | The engine path works on Windows. |
| **P1 Agent control** | Operation API + MCP server. Claude Code can build/edit a timeline and export it with no GUI. | The core differentiator, front-loaded. |
| **P2 Generation** | `GenerationProvider` + ComfyUI local (image, then LTX-Video) + one cloud provider. Agent: "generate X → place on timeline." | Local-first + cloud-optional thesis. |
| **P3 GUI** | Web frontend: timeline, preview player, media bin, generation panel, agent chat. Interactive render backend for scrubbing. | Ordinary-user usability. |
| **P4 Depth** | Effects/transitions/color, semantic media search, packaging/installer, docs, OSS release hygiene. | Ready for the world. |

The P0→P2 headless demo — *"Claude, generate a 5-second sunrise, put it at 0:12, and export a 1080p
cut"* — is the proof-of-concept that de-risks the entire vision before a single pixel of GUI exists.

---

## 10. Open decisions (deliberately unmade)

- Interactive render backend: **libopenshot vs MLT** — decide when P3 starts, against real preview needs.
- Cloud aggregator: **Replicate vs fal.ai** — decide when P2 starts, against model coverage + pricing.
- Desktop shell: **Tauri vs pywebview vs Electron** — decide when P3 starts, against packaging weight.
- These are recorded as open on purpose; committing early would be guessing.
