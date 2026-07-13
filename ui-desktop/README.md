# Opmiere desktop (Tauri)

**Product shell** for the human surface. Python `Editor` remains the source of truth;
this app is a WebView client over the local HTTP API (`opmiere web`).

See `docs/ADR_UI_AND_PREVIEW.md`.

## Requirements

- Node 18+
- Rust stable (`rustup`) — first `tauri dev` compiles the host
- **Windows:** Visual Studio **Build Tools** with C++ workload (`link.exe` / MSVC). Rustup alone is not enough.  
  Verified: VS 2022 BuildTools + `vcvars64.bat` → `cargo check` succeeds.
- Opmiere with web extras: `pip install -e ".[web]"`

## Dev

From repo root (starts API + Tauri):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
```

Or two terminals:

```powershell
# terminal 1 — core API
python -m opmiere.web.app

# terminal 2 — shell
cd ui-desktop
npm install
npm run tauri dev
```

Optional: `VITE_OPMIERE_API=http://127.0.0.1:8787` (default).

## Scope (0.4.x)

| In | Out |
|----|-----|
| Window chrome + design tokens | Agent chat panel |
| Program monitor scrub + play (proxy / OpenShot stills) | Full realtime effects play |
| Full NLE craft shell + native Open/New dialogs | Embedded Python core in installer |
| **Windows NSIS installer** (`scripts/build-desktop.ps1`) | Code-signing / auto-update |

### Program monitor

After core API is up and **Demo project** (or any open project):

1. Scrub bar / ◀ ▶ / click timeline lane  
2. Engine: `auto` (OpenShot if installed) · `openshot` · `proxy` · `base`

## Release build (Windows installer)

From repo root (loads VS Build Tools `vcvars64` when present):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

Artifacts:

- `ui-desktop/src-tauri/target/release/opmiere-desktop.exe` — portable shell
- `ui-desktop/src-tauri/target/release/bundle/nsis/*.exe` — NSIS installer

Or from `ui-desktop/`:

```powershell
npm run tauri:build
```

**Runtime:** the shell still expects Python core on `http://127.0.0.1:8787`:

```powershell
pip install -e ".[web]"
python -m opmiere.web.app
```

## Layout

```
ui-desktop/
  src/           # Vite TS frontend
  src-tauri/     # Tauri host + NSIS bundle config
scripts/
  dev-desktop.ps1
  build-desktop.ps1
```
