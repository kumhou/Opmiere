# Build Opmiere desktop (Tauri) release + Windows NSIS installer.
# Requires: Node, Rust, VS Build Tools (link.exe), WebView2.
# Usage (repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
# Optional:
#   -SkipBundle   cargo/tauri build without installer packaging
#   -Targets nsis  (default)

param(
    [switch]$SkipBundle,
    [string]$Targets = "nsis"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Desktop = Join-Path $Root "ui-desktop"

Write-Host "== Opmiere desktop build ==" -ForegroundColor Cyan
Write-Host "Root: $Root"

# Prefer cargo from rustup (must be on PATH for `tauri build` child processes)
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$Cargo = Join-Path $CargoBin "cargo.exe"
if (Test-Path $CargoBin) {
    if ($env:Path -notlike "*$CargoBin*") {
        $env:Path = "$CargoBin;$env:Path"
    }
}
if (-not (Test-Path $Cargo)) {
    $Cargo = "cargo"
}

# MSVC environment (Windows)
$vcvarsCandidates = @(
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
)
$vcvars = $vcvarsCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($vcvars) {
    Write-Host "Loading MSVC env: $vcvars"
    # Export env from vcvars into this process
    $tmp = [System.IO.Path]::GetTempFileName() + ".cmd"
    @"
@echo off
call "$vcvars" >nul
set > "$env:TEMP\opmiere_vcvars_env.txt"
"@ | Set-Content -Path $tmp -Encoding ASCII
    & cmd.exe /c $tmp
    Remove-Item $tmp -ErrorAction SilentlyContinue
    Get-Content "$env:TEMP\opmiere_vcvars_env.txt" | ForEach-Object {
        if ($_ -match "^(.*?)=(.*)$") {
            $name = $matches[1]
            $val = $matches[2]
            if ($name -and $name -notmatch "^\s*$") {
                [System.Environment]::SetEnvironmentVariable($name, $val, "Process")
            }
        }
    }
    # vcvars overwrites PATH — re-prepend cargo bin
    if (Test-Path $CargoBin) {
        $env:Path = "$CargoBin;$env:Path"
    }
} else {
    Write-Warning "vcvars64.bat not found — build may fail without MSVC link.exe"
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo not found on PATH (install rustup and retry)"
}
Write-Host "cargo: $((Get-Command cargo).Source)"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "node not found"
}

Push-Location $Desktop
try {
    if (-not (Test-Path "node_modules")) {
        Write-Host "npm install..."
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    }

    Write-Host "Frontend + Tauri release build (targets=$Targets)..."
    if ($SkipBundle) {
        npx tauri build --no-bundle
    } else {
        npx tauri build --bundles $Targets
    }
    if ($LASTEXITCODE -ne 0) { throw "tauri build failed ($LASTEXITCODE)" }

    $bundleDir = Join-Path $Desktop "src-tauri\target\release\bundle"
    $exe = Join-Path $Desktop "src-tauri\target\release\opmiere-desktop.exe"
    Write-Host ""
    Write-Host "Build OK" -ForegroundColor Green
    if (Test-Path $exe) { Write-Host "  exe: $exe" }
    if (Test-Path $bundleDir) {
        Write-Host "  bundle:"
        Get-ChildItem $bundleDir -Recurse -File -Include *.exe,*.msi,*.nsis.zip -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "    $($_.FullName)" }
    }
    Write-Host ""
    Write-Host "Note: shell talks to Python core API (default http://127.0.0.1:8787)."
    Write-Host "  pip install -e `".[web]`" then: python -m opmiere.web.app"
} finally {
    Pop-Location
}
