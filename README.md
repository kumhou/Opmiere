# Opmiere

**Open Premiere** — an open-source, agent-native video editor for Windows.

Edit video the normal way with a GUI, **or** let an AI agent (Claude Code, Cursor, any
[MCP](https://modelcontextprotocol.io) client) drive the *same* editing engine: "cut the dead air,
generate a sunrise B-roll, drop it at 0:12, color-match the previous shot, export 1080p."

Generative AI (image / video / audio) runs **locally on your own GPU first** via
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) — free, private, unlimited iteration — with
**paid cloud APIs (Runway, Kling, Sora, Flux, ElevenLabs) as an optional quality boost**. Cheap local
drafts; pay only for the shots you commit to.

> **Status: 0.7.6.** Headless NLE + MCP + path-C OpenShot preview (install optional) + **Tauri product shell** (`ui-desktop/` — primary human GUI). HTML `opmiere web` remains a dogfood / API host.
> Product is the **NLE**; director/style is a **hero feature**. Dual surface: human GUI + agent MCP on one Editor.
> See [CHANGELOG.md](CHANGELOG.md), [docs/ADR_UI_AND_PREVIEW.md](docs/ADR_UI_AND_PREVIEW.md), [docs/TOOLS.md](docs/TOOLS.md), [docs/CI.md](docs/CI.md).

## Install (Windows, native — no Docker)

From a clone of this repo (Python 3.10+ and [FFmpeg](https://ffmpeg.org/download.html) on PATH):

```powershell
# Recommended: venv under %LOCALAPPDATA%\Opmiere + User PATH
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Extras web

opmiere doctor          # must report core ok
opmiere web             # Core API :8787 (desktop auto-starts this)
opmiere mcp             # MCP stdio server for agents

# Product shell (human GUI) — needs Node/Rust for first build
powershell -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
# Release NSIS: .\scripts\build-desktop.ps1

# Remove the install (keeps this git checkout)
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

Editable install only (no PATH / marker):

```bash
pip install -e ".[web]"
python -m opmiere doctor
```

Optional extras: `[transcribe]` faster-whisper, `[scenes]` PySceneDetect, `[stems]` demucs, `[all]`.

### CLI

| Command | Purpose |
|---------|---------|
| `opmiere doctor` | ffmpeg, Python, extras, ComfyUI port |
| `opmiere version` | package version |
| `opmiere web` | Core API + HTML dogfood probe (`:8787`) |
| `opmiere mcp` | MCP server (same as `opmiere-mcp`) |
| `scripts/dev-desktop.ps1` | Tauri product shell + ensure Core API |

### Local CI (canonical — no GitHub-hosted minutes)

Private-repo GitHub Actions minutes are **not** used for every push. Gate on this machine:

```powershell
# Full gate (doctor + pytest + dogfood pipelines)
powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1

# Fast gate before a small push
powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1 -Quick

# Optional: pre-push hook runs -Quick
powershell -ExecutionPolicy Bypass -File .\scripts\install-ci-hook.ps1
```

Optional free GitHub path: self-hosted Windows runner + manual `workflow_dispatch` only — see [docs/CI.md](docs/CI.md).

### Pro pipeline dogfood (no ComfyUI)

```bash
python scripts/dogfood_pro_pipeline.py
# → scripts/_dogfood_pro_out/{report.json,checklist.md,export*}

python scripts/dogfood_template_pipeline.py --template talking_head
# agent default path (preflight → finish_session)
python scripts/dogfood_agent_pipeline.py
# → scripts/_dogfood_template_out/  (template → finish_delivery)
# Exit 0 only if hard gates pass.
```

Agent docs: [docs/TOOLS.md](docs/TOOLS.md) · [docs/AGENT_WARNINGS.md](docs/AGENT_WARNINGS.md)

## Why

Open-source editors (Shotcut, Kdenlive, OpenShot) have no agent interface. Palmier Pro (GPL-3.0)
pioneered the agent-native NLE, but it is macOS / Apple-Silicon only and its generation leans on cloud
APIs. Both projects are open source — Opmiere's difference is **Windows + NVIDIA/CUDA with local-GPU
generation as the core capability**: making a modest 8 GB card reach high quality via quantization and
memory offload (trading time for quality), built for creators priced out of cloud AI subscriptions who
have a capable GPU sitting idle.

## Design in one breath

- **API-first headless core** — the GUI and the AI agent are both clients of one shared operation API.
  Anything a human can do, an agent can do, by construction.
- **Engine-independent project model** — Opmiere owns its timeline; render engines (FFmpeg now,
  libopenshot/MLT later) are pluggable backends.
- **Everything is a provider** — local ComfyUI and cloud APIs implement one generation interface for
  image, video, **and audio (TTS / SFX / music)**; the user picks per shot.
- **Editor-first, generation-additive** — a curated deterministic toolset (cut, color, chroma key,
  transitions, text, audio) means quality does *not* depend only on AI generation; the agent does
  reliable tool-work and reserves generation for genuinely-new imagery.

See [ARCHITECTURE.md](ARCHITECTURE.md).

## Reference hardware

Developed against **NVIDIA RTX 3070 (8 GB) / 32 GB RAM / Windows 11**. Local image generation is
comfortable; local video generation targets lightweight models (LTX-Video); heavier video is expected
via cloud providers. Bigger GPUs simply unlock more local capability — the architecture is the same.

## Stack

Python core · MCP server · FFmpeg / libopenshot render backends · ComfyUI + cloud generation providers
· web GUI (planned).

## License

[Apache-2.0](LICENSE). Bundled GPL/LGPL engines (FFmpeg, MLT) are invoked at arms length as separate
processes and are not part of Opmiere's own licensed code.
