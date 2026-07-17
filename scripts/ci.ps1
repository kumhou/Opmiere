#Requires -Version 5.1
<#
.SYNOPSIS
  Opmiere local CI — canonical gate (no GitHub-hosted Actions minutes).

.DESCRIPTION
  Replaces GitHub-hosted windows-latest CI for this private repo.
  Run before push / after meaningful changes:

    powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1 -Quick
    powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1 -SkipDogfood

  Exit 0 only if all enabled steps pass.

.PARAMETER Quick
  Doctor + pytest only (no dogfood pipelines).

.PARAMETER SkipDogfood
  Doctor + pytest; skip dogfood scripts.

.PARAMETER PytestArgs
  Extra args passed to pytest (default: tests/ -q --tb=line).
#>
[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$SkipDogfood,
    [string[]]$PytestArgs = @("tests/", "-q", "--tb=line")
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:OPMIERE_SKIP_COMFY = "1"

function Step([string]$Name, [scriptblock]$Body) {
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit $LASTEXITCODE)"
    }
}

Write-Host "Opmiere local CI  root=$Root" -ForegroundColor Green
Write-Host "Python: $(python --version 2>&1)"
Write-Host "ffmpeg: $(ffmpeg -version 2>&1 | Select-Object -First 1)"

Step "Doctor (no ComfyUI)" {
    python -m opmiere doctor --no-comfy --json
}

Step "Pytest" {
    python -m pytest @PytestArgs
}

if (-not $Quick -and -not $SkipDogfood) {
    Step "Dogfood pro pipeline" {
        python scripts/dogfood_pro_pipeline.py --seconds 1.5
    }
    Step "Dogfood cut template" {
        python scripts/dogfood_template_pipeline.py --seconds 1.2 --template talking_head
    }
    Step "Dogfood agent session" {
        python scripts/dogfood_agent_pipeline.py --seconds 1.2 --template talking_head
    }
}

Write-Host ""
Write-Host "CI OK" -ForegroundColor Green
exit 0
