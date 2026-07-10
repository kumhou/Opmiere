#Requires -Version 5.1
<#
.SYNOPSIS
  Remove native Opmiere install created by install.ps1.

.DESCRIPTION
  Deletes %LOCALAPPDATA%\Opmiere (venv + marker) and strips Scripts from User PATH.
  Does NOT uninstall system Python or ffmpeg. Does NOT delete the git checkout.
#>
param(
    [switch]$KeepMarker,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$InstallRoot = Join-Path $env:LOCALAPPDATA "Opmiere"
$VenvDir = Join-Path $InstallRoot "venv"
$Scripts = Join-Path $VenvDir "Scripts"
$MarkerPath = Join-Path $InstallRoot "install.json"

if (-not $Yes) {
    $ans = Read-Host "Remove Opmiere venv at $InstallRoot ? [y/N]"
    if ($ans -notmatch '^[yY]') {
        Write-Host "aborted"
        exit 0
    }
}

Write-Host "==> Strip User PATH entry for $Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $parts = $userPath -split ";" | Where-Object { $_ -and ($_ -ne $Scripts) }
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
}

if (Test-Path $InstallRoot) {
    Write-Host "==> Remove $InstallRoot"
    # venv on Windows can lock python.exe briefly
    Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($VenvDir, [StringComparison]::OrdinalIgnoreCase)
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallRoot) {
        Write-Warning "Could not fully delete $InstallRoot — close apps using the venv and retry"
        exit 1
    }
} else {
    Write-Host "    (nothing at $InstallRoot)"
}

Write-Host "Uninstall done. Repo checkout left untouched." -ForegroundColor Green
