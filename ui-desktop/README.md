# Opmiere desktop (Tauri)

**Product shell** for the human surface. Python `Editor` remains the source of truth;
this app is a WebView client over the local HTTP API (`opmiere web`).

See `docs/ADR_UI_AND_PREVIEW.md`.

## Requirements

- Node 18+
- Rust stable (`rustup`) — first `tauri dev` compiles the host
- **Windows:** Visual Studio **Build Tools** with “Desktop development with C++” (`link.exe` / MSVC). Rustup alone is not enough.
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

## Scope (0.4 scaffold)

| In | Out |
|----|-----|
| Window chrome + design tokens | Full timeline craft (still Python) |
| Status: doctor / preview engine / timeline snapshot | Agent chat panel |
| Link to HTML probe | Shipping installer polish |

## Layout

```
ui-desktop/
  src/           # Vite TS frontend
  src-tauri/     # Tauri host
```
