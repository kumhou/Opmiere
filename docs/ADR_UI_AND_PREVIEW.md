# ADR: UI shell + interactive preview (2026-07-12)

**Status:** Accepted (JH)  
**Supersedes:** informal “HTML shell = product UI” reading of 0.3.0; hybrid FFmpeg-composite preview path (rejected)

## Context

Opmiere is an agent-native **NLE**. Core (`Editor` / Project / MCP / FFmpeg delivery) is the durable product. A large FastAPI + `index.html` shell proved dual-surface and design tokens, but is not a sustainable end-state UI. Interactive preview must be a real NLE engine (path C), not a dual-mode FFmpeg “composite on stale” detour that would force a later rebuild.

## Decisions

### Preview engine

| Item | Decision |
|------|----------|
| Product path | **C — true interactive backend** |
| Preference | **libopenshot** (LGPL-linkable NLE library) |
| Alternative | MLT if Windows/Python packaging or stability fails spike |
| Explicitly rejected | Path B: hybrid FFmpeg composite dual-mode as product scrub path |
| Delivery export | Remains **FFmpeg** (`RenderBackend`); preview ≠ delivery |
| Process | Preference is not a lock — **spike** (seek → one frame on Windows) before adapter investment |

### UI layers

| Layer | Role | Policy |
|-------|------|--------|
| A Core | `Editor`, Project, Operations | Forever |
| B Protocol | Timeline JSON, PreviewSession state machine, command names, shortcuts | Forever — any shell consumes this |
| C Design system | `design-system/opmiere` tokens & craft density | Forever — reimplement, don’t redesign from zero |
| D HTML probe | `opmiere-web` + `static/index.html` | **Maintenance / dogfood only** — no feature expansion by default |
| E Product shell | Tauri desktop + WebView chrome + native preview bridge | **End-state human UI** |

### Product shell (E)

| Item | Decision |
|------|----------|
| Host | **Tauri** (Windows-first) |
| Chrome / timeline | **Web tech in WebView** (TS/HTML/CSS OK) — density from design system |
| Preview surface | Engine frames via **local bridge** (not HTML5 `<video>` as sole truth) |
| Agent in GUI (v1) | **No chat panel** — human cuts in GUI; agents via external MCP |
| Dual surface | GUI and MCP are clients of the same `Editor` — no GUI-private edit semantics |

### HTML probe gate (D)

**Allowed:** bugfixes that unblock dogfood; tiny API smoke controls; token tweaks.  
**Default reject:** new timeline interaction systems; “make proxy scrub feel like Premiere”; business logic only in `index.html`.

### PreviewSession contract (target API shape)

Shell and agents share semantics (implementation later):

- States: `unavailable | idle | seeking | playing | error`
- Ops: open(project) · seek(t) · play/pause · frame_jpeg(t)? · close · capabilities
- UI binds transport/playhead to this session; proxy.mp4 may remain a **fallback**, labeled, never the final look model

## Priority order (owner: engineering, JH-aligned)

1. **ADR + ARCHITECTURE alignment** (this doc) — done  
2. **libopenshot Windows spike** — done; report: [SPIKE_LIBOPENSHOT_WINDOWS.md](SPIKE_LIBOPENSHOT_WINDOWS.md)  
   - In-process import on CPython 3.10: **no**; OpenShot ships MinGW 3.8 `_openshot.pyd`  
   - Next packaging: **S2 sidecar** then **S1 wheel**; **S3 MLT** if blocked  
3. **PreviewSession interface** in core (stub OK) + MCP/docs; no fake realtime claims  
4. **Core NLE gaps** that block craft (only if spike blocked / between spikes) — Editor/MCP/tests first  
5. **Tauri product shell scaffold** — empty window, talk to core API, design tokens, **no** agent chat  
6. **OpenShot adapter vertical slice** — single track → multi-track → mapped effects  
7. **Retire HTML as default UX** — keep for CI/smoke if useful; product entry is Tauri  

Do **not** run a parallel “HTML 0.3.x polish” track.

## Consequences

- 0.3.0 “UI shell complete” = **probe checklist complete**, not shipping GUI done.  
- Investment goes to core + engine spike + Tauri, not `index.html` feature velocity.  
- Choosing openshot preference may still flip to MLT after spike data — **PreviewSession** stays stable either way.  
- Agent-native story unchanged: MCP remains first-class; GUI is the human client.

## References

- `ARCHITECTURE.md` §5.2, §5.4, §10  
- `design-system/opmiere/MASTER.md`  
- Vision: NLE craft base first; director is hero feature only  
