#Requires -Version 5.1
<#
.SYNOPSIS
  Install a local git pre-push hook that runs scripts/ci.ps1 -Quick.

.DESCRIPTION
  Does not use GitHub Actions. Optional — for humans who want a push gate.
  Bypass once:  git push --no-verify
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$HookDir = Join-Path $Root ".git\hooks"
$Hook = Join-Path $HookDir "pre-push"

if (-not (Test-Path (Join-Path $Root ".git"))) {
    throw "Not a git repo: $Root"
}
New-Item -ItemType Directory -Force -Path $HookDir | Out-Null

# Literal shell script body (no PowerShell expansion)
$hookBody = @'
#!/bin/sh
# Opmiere local CI gate (installed by scripts/install-ci-hook.ps1)
# Skip: git push --no-verify
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT" || exit 1
powershell.exe -ExecutionPolicy Bypass -File "./scripts/ci.ps1" -Quick
exit $?
'@

$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($Hook, $hookBody.Replace("`r`n", "`n"), $utf8)

Write-Host "Installed pre-push -> $Hook" -ForegroundColor Green
Write-Host "Runs: scripts/ci.ps1 -Quick on every push. Bypass: git push --no-verify"
