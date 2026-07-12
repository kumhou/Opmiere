# Start Opmiere core API + Tauri product shell (dev).
# Requires: Python opmiere[web], Node, Rust/cargo (for first tauri build).
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "ui-desktop\package.json"))) {
    throw "ui-desktop not found under $Root"
}

$env:Path = "$env:USERPROFILE\.cargo\bin;" + $env:Path

Write-Host "Starting opmiere web API on http://127.0.0.1:8787 ..."
$api = Start-Process -FilePath "python" -ArgumentList "-m","opmiere.web.app" `
    -WorkingDirectory $Root -PassThru -WindowStyle Minimized

Start-Sleep -Seconds 1
try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:8787/api/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "API ok"
} catch {
    Write-Host "API not responding yet (continuing) — $_"
}

Push-Location (Join-Path $Root "ui-desktop")
try {
    if (-not (Test-Path "node_modules")) {
        Write-Host "npm install..."
        npm install
    }
    Write-Host "tauri dev (Ctrl+C stops UI; stop API PID $($api.Id) separately if needed)"
    npm run tauri dev
} finally {
    Pop-Location
    if ($api -and -not $api.HasExited) {
        Write-Host "Stopping API PID $($api.Id)"
        Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    }
}
