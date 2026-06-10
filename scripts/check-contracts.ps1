# Fails when the committed contract artifacts are stale (i.e. regenerating
# them produces a diff). Intended as a local/CI gate.
# NOTE: never hand-merge the generated files on conflicts - regenerate instead.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot "gen-contracts.ps1")

Push-Location $repoRoot
try {
    $generated = @(
        "frontend/src/renderer/src/types/generated/openapi.json",
        "frontend/src/renderer/src/types/generated/api.d.ts"
    )
    $dirty = git status --porcelain -- $generated
    if ($LASTEXITCODE -ne 0) { throw "git status failed (exit $LASTEXITCODE)" }
    if ($dirty) {
        $dirty | Write-Host
        throw "Contract artifacts are stale: run scripts/gen-contracts.ps1 and commit the result."
    }
} finally {
    Pop-Location
}

Write-Host "Contracts are up to date." -ForegroundColor Green
