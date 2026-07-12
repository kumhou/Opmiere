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
| Window chrome + design tokens | Full NLE edit gestures |
| Status: doctor / preview engine / timeline snapshot | Agent chat panel |
| **Program monitor scrub + play** (proxy video / stepped OpenShot) | Full realtime effects play |
| **Full edit shell loop**: New/Open/Save, Import/place, Razor, Mark/Mute, track M/S/L/+V/+A, drag/trim/multi/Export | Native dialogs, installer, agent chat |
| Demo project + timeline click seek | Shipping installer polish |

### Program monitor

After core API is up and **Demo project** (or any open project):

1. Scrub bar / ◀ ▶ / click timeline lane  
2. Engine: `auto` (OpenShot if installed) · `openshot` · `proxy` · `base`

## Layout

```
ui-desktop/
  src/           # Vite TS frontend
  src-tauri/     # Tauri host
```
