# Opmiere

**Open Premiere** — an open-source, agent-native video editor for Windows.

Edit video the normal way with a GUI, **or** let an AI agent (Claude Code, Cursor, any
[MCP](https://modelcontextprotocol.io) client) drive the *same* editing engine: "cut the dead air,
generate a sunrise B-roll, drop it at 0:12, color-match the previous shot, export 1080p."

Generative AI (image / video / audio) runs **locally on your own GPU first** via
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) — free, private, unlimited iteration — with
**paid cloud APIs (Runway, Kling, Sora, Flux, ElevenLabs) as an optional quality boost**. Cheap local
drafts; pay only for the shots you commit to.

> **Status: pre-alpha / design phase.** Not usable yet. See [ARCHITECTURE.md](ARCHITECTURE.md) for the
> full design and roadmap.

## Why

Open-source editors (Shotcut, Kdenlive, OpenShot) have no agent interface. Palmier Pro pioneered the
agent-native NLE but is macOS-only, closed-source, and subscription-gated for generation. Opmiere is
the open, Windows-first, local-GPU answer — built for creators priced out of cloud AI subscriptions
who have a capable GPU already.

## Design in one breath

- **API-first headless core** — the GUI and the AI agent are both clients of one shared operation API.
  Anything a human can do, an agent can do, by construction.
- **Engine-independent project model** — Opmiere owns its timeline; render engines (FFmpeg now,
  libopenshot/MLT later) are pluggable backends.
- **Everything is a provider** — local ComfyUI and cloud APIs implement one generation interface; the
  user picks per shot.

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
