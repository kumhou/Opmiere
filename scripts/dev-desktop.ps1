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

# MSVC link.exe required for Tauri on Windows (VS Build Tools / VCTools workload)
$vcvars = @(
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $vcvars) {
    Write-Host "WARN: vcvars64.bat not found — install VS 2022 Build Tools with C++ workload."
    Write-Host "  winget install Microsoft.VisualStudio.2022.BuildTools --override `"--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`""
} else {
    Write-Host "Loading MSVC env: $vcvars"
    # Import vcvars into this PowerShell session
    $tmp = [System.IO.Path]::GetTempFileName() + ".cmd"
    @"
@echo off
call "$vcvars" >nul
set > "$tmp.env"
"@ | Set-Content -Path $tmp -Encoding ASCII
    cmd /c $tmp | Out-Null
    $envFile = "$tmp.env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
        Remove-Item $envFile -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    if (-not (Get-Command link -ErrorAction SilentlyContinue)) {
        Write-Host "WARN: link.exe still not on PATH after vcvars"
    } else {
        Write-Host "MSVC link.exe ok"
    }
}

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
    Write-Host "tauri dev (Ctrl+C stops UI; API PID $($api.Id))"
    npm run tauri dev
} finally {
    Pop-Location
    if ($api -and -not $api.HasExited) {
        Write-Host "Stopping API PID $($api.Id)"
        Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    }
}
