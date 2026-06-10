# Fails when the committed contract artifacts are stale (i.e. regenerating
# them produces a diff). Intended as a local/CI gate.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot "gen-contracts.ps1")

Push-Location $repoRoot
try {
    $dirty = git status --porcelain -- frontend/src/renderer/src/types/generated
    if ($dirty) {
        Write-Host $dirty
        throw "Contract artifacts are stale: run scripts/gen-contracts.ps1 and commit the result."
    }
} finally {
    Pop-Location
}

Write-Host "Contracts are up to date." -ForegroundColor Green
