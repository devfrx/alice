# ──────────────────────────────────────────────────
# AL\CE — Install entry point (Windows)
# ──────────────────────────────────────────────────
# Thin wrapper that delegates to setup.ps1 so users who reach for an
# "install" script land on the canonical setup flow. Forwards every flag.
#
# Examples:
#   .\scripts\install.ps1
#   .\scripts\install.ps1 -CpuOnly
#   .\scripts\install.ps1 -SkipModels -SkipFrontend

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Setup     = Join-Path $ScriptDir "setup.ps1"

if (-not (Test-Path $Setup)) {
    Write-Host "  [X] setup.ps1 not found at: $Setup" -ForegroundColor Red
    exit 1
}

& $Setup @ForwardArgs
exit $LASTEXITCODE
