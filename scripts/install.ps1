#Requires -Version 5.1
<#
.SYNOPSIS
  Native Windows install for Opmiere (venv + editable package + doctor).

.DESCRIPTION
  Does NOT use Docker. Creates %LOCALAPPDATA%\Opmiere\venv, installs this repo
  editable, writes install.json, optionally prepends Scripts to User PATH.
  Re-run safely to upgrade.

.PARAMETER Extras
  pip extras: none | web | all | dev  (default: web)

.PARAMETER SkipPath
  Do not modify User PATH.

.PARAMETER RepoRoot
  Path to Opmiere checkout (default: parent of scripts/).
#>
param(
    [ValidateSet("none", "web", "all", "dev", "transcribe", "scenes")]
    [string]$Extras = "web",
    [switch]$SkipPath,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    throw "Not an Opmiere repo (no pyproject.toml): $RepoRoot"
}

$InstallRoot = Join-Path $env:LOCALAPPDATA "Opmiere"
$VenvDir = Join-Path $InstallRoot "venv"
$MarkerPath = Join-Path $InstallRoot "install.json"
$Python = $null

Write-Step "Locate Python >= 3.10"
foreach ($cand in @("py", "python", "python3")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
            if ($ver -match '^(\d+)\.(\d+)$' -and ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10))) {
                $Python = $cmd.Source
                if ($cand -eq "py") { $Python = "py" }  # keep launcher
                Write-Ok "using $cand ($ver)"
                break
            }
        } catch { }
    }
}
if (-not $Python) { throw "Python 3.10+ not found on PATH" }

Write-Step "Check ffmpeg / ffprobe"
foreach ($tool in @("ffmpeg", "ffprobe")) {
    $t = Get-Command $tool -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Warn "$tool not on PATH — install from https://ffmpeg.org/download.html (core edit will fail doctor)"
    } else {
        Write-Ok "$tool = $($t.Source)"
    }
}

Write-Step "Create venv at $VenvDir"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    if ($Python -eq "py") {
        & py -3 -m venv $VenvDir
    } else {
        & $Python -m venv $VenvDir
    }
}
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
if (-not (Test-Path $VenvPy)) { throw "venv python missing: $VenvPy" }

Write-Step "Upgrade pip"
& $VenvPy -m pip install --upgrade pip setuptools wheel | Out-Host

$spec = switch ($Extras) {
    "none" { "" }
    "web"  { ".[web]" }
    "all"  { ".[all]" }
    "dev"  { ".[dev,web]" }
    "transcribe" { ".[transcribe]" }
    "scenes" { ".[scenes]" }
}
Write-Step "pip install -e $spec from $RepoRoot"
Push-Location $RepoRoot
try {
    if ($spec) {
        & $VenvPy -m pip install -e $spec | Out-Host
    } else {
        & $VenvPy -m pip install -e . | Out-Host
    }
} finally {
    Pop-Location
}

$marker = @{
    installed_at = (Get-Date).ToString("o")
    repo_root    = $RepoRoot
    venv         = $VenvDir
    extras       = $Extras
    python       = $VenvPy
    version_cmd  = "$VenvPy -m opmiere.cli version"
}
$marker | ConvertTo-Json | Set-Content -Path $MarkerPath -Encoding UTF8
Write-Ok "wrote $MarkerPath"

if (-not $SkipPath) {
    Write-Step "User PATH: prepend venv Scripts"
    $scripts = Join-Path $VenvDir "Scripts"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    $parts = $userPath -split ";" | Where-Object { $_ -and $_ -ne $scripts }
    $newPath = ($scripts + ";" + ($parts -join ";")).TrimEnd(";")
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = $scripts + ";" + $env:Path
    Write-Ok "PATH updated (new shells pick this up)"
}

Write-Step "opmiere doctor"
& $VenvPy -m opmiere.cli doctor --no-comfy
$docExit = $LASTEXITCODE

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "  opmiere doctor"
Write-Host "  opmiere web          # if [web] installed"
Write-Host "  opmiere mcp          # MCP stdio server"
Write-Host "  uninstall:  powershell -File `"$PSScriptRoot\uninstall.ps1`""
if ($docExit -ne 0) {
    Write-Warn "doctor reported core issues — fix ffmpeg/PATH then re-run: opmiere doctor"
    exit $docExit
}
