# Spike: libopenshot on Windows (2026-07-12)

**Goal:** Can Opmiere call libopenshot from our process for path-C interactive preview  
(seek → one composite frame)?  
**Machine:** Windows, CPython **3.10.7** (Opmiere), OpenShot Video Editor **3.5.1** via winget.  
**Preference:** libopenshot (JH); MLT remains documented fallback.

## What we installed / found

| Artifact | Location / note |
|----------|-----------------|
| OpenShot 3.5.1 | `C:\Program Files\OpenShot Video Editor\` |
| libopenshot | **0.7.0** (`settings/libopenshot.env`, SO 30) |
| Python extension | `lib\_openshot.pyd` (~3.5 MB) |
| Core DLLs | `lib\libopenshot.dll`, `lib\libopenshot-audio.dll` |
| Bundled interpreter | **MinGW `libpython3.8.dll`** + full FFmpeg/Qt/OpenCV stack under `lib\` |
| App entry | Frozen `openshot-qt.exe` / `openshot-qt-cli.exe` (GUI flags only — **no** headless frame CLI) |
| pip | `openshot` / `openshot-qt` — **no matching distribution** on PyPI for this environment |
| conda | not available on this machine |
| MSYS2 / full rebuild toolchain | **not** installed (no cmake/swig/g++ in PATH) |

## Experiments

### 1. Import into Opmiere’s Python 3.10

```text
import openshot  →  ModuleNotFoundError (no wheel)
```

### 2. CPython 3.8.10 embeddable (MSVC) + OpenShot `lib\` on PATH / PYTHONPATH

- `ctypes.CDLL(libopenshot-audio.dll)` → **ok**
- `ctypes.CDLL(libopenshot.dll)` → **ok** (DLL dependency tree resolves)
- `import _openshot` → process **access violation** (`0xC0000005`, exit `-1073741819`)

**Root cause:** `_openshot.pyd` is linked against OpenShot’s **MinGW** `libpython3.8.dll`, not stock CPython’s `python38.dll`. ABI/runtime mismatch → crash, not a clean ImportError.

### 3. `openshot-qt-cli.exe`

Help only: language, web-backend, debug, version. **No** export/seek/frame subcommands for embedding.

### 4. Source build path (not executed)

Official `INSTALL-WINDOWS.md` requires MSYS2 + Qt + FFmpeg + SWIG + libopenshot-audio + many deps, then cmake/mingw. Multi-hour to multi-day; must target **our** Python (3.10) if we want in-process import.

## Conclusions

| Question | Answer |
|----------|--------|
| Is libopenshot “real” on Windows? | **Yes** — ships with OpenShot 3.5.1 (0.7.0), actively maintained (2026 releases). |
| Can Opmiere 3.10 import it today? | **No** without a dedicated build or sidecar. |
| Is “just install OpenShot and import” viable? | **No** — frozen MinGW 3.8 stack ≠ our interpreter. |
| Is path C blocked forever? | **No** — blocked on **packaging**, not on engine capability. |
| Should we do hybrid FFmpeg dual-mode (path B)? | **Still no** (ADR). Keep proxy as interim only. |

## Viable integration strategies (ranked for sustainability)

### S1 — Vendor wheel / CI build (preferred long-term)

Build `libopenshot` + SWIG bindings against **Opmiere’s Python** (3.10+), ship as optional wheel or install script (MSYS2 or MSVC matrix).

- **Pros:** In-process PreviewSession; clean API (`Timeline`, `Clip`, `FFmpegReader`, …).  
- **Cons:** Serious CI/Windows engineering; version pin to OpenShot release train.  
- **Effort:** High (weeks, not hours).

### S2 — Sidecar process with OpenShot-compatible runtime

Small helper process that either:

- uses a **frozen/minigw Python 3.8** environment we control (built once), or  
- is a thin C++/Rust tool linking `libopenshot.dll` and speaking JSON/stdio frames.

- **Pros:** Opmiere stays on 3.10; PreviewSession talks RPC; license still LGPL-linkable in sidecar.  
- **Cons:** IPC latency; packaging still copies a large DLL tree.  
- **Effort:** Medium–high; good bridge while S1 matures.

### S3 — MLT / Shotcut `melt` fallback (if S1/S2 stall)

Process-level `melt` + XML playlist (Shotcut on winget: `Meltytech.Shotcut`).

- **Pros:** Proven NLE engine; arms-length process matches ARCHITECTURE license posture for MLT.  
- **Cons:** Different mapping model; second engine to learn.  
- **Trigger:** Openshot packaging fails two dedicated attempts or blocks Tauri preview >N weeks.

### Explicitly rejected for product scrub

- Dual-mode FFmpeg “composite frame when proxy stale” as the **product** interactive path (path B).  
- Treating HTML5 proxy `<video>` as final look model.

## Recommended next steps (aligned with ADR priority)

1. **Freeze PreviewSession interface** in Opmiere (stub + `unavailable` backend) — no fake realtime.  
2. **Choose packaging track:** default **S2 sidecar spike next** (faster proof of seek→JPEG using OpenShot’s DLL tree without hijacking 3.10), design so S1 can replace the process with in-process later.  
3. Do **not** expand HTML shell.  
4. Defer Tauri scaffold until PreviewSession + one working frame path (stub or sidecar) exists.  
5. Keep OpenShot 3.5.1 installed on the dev machine as reference binary/DLL tree (optional; not a runtime dep for users until we vendor).

## Spike success criteria (original) vs result

| Criterion | Result |
|-----------|--------|
| Import bindings | **Fail** on Opmiere Python |
| Minimal timeline + seek → JPEG | **Not reached** (blocked by import) |
| Record fail conditions for MLT | **Done** — see S3 trigger above |
| Decision quality | **Enough to plan packaging** without committing to path B |

## References

- OpenShot install: winget `OpenShot.OpenShot` 3.5.1  
- libopenshot version env: `…\OpenShot Video Editor\settings\libopenshot.env`  
- Build docs: libopenshot `INSTALL-WINDOWS.md` (MSYS2)  
- Product ADR: [ADR_UI_AND_PREVIEW.md](ADR_UI_AND_PREVIEW.md)
