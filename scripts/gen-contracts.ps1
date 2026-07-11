# Regenerates the FE<->BE contract artifacts:
#   1. backend OpenAPI schema -> frontend/src/renderer/src/types/generated/openapi.json
#   2. openapi-typescript     -> frontend/src/renderer/src/types/generated/api.d.ts
# Run from anywhere; requires the repo venv (.venv) and frontend npm deps installed.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv python not found at $python - run scripts\setup.ps1 first" }
$schemaPath = Join-Path $repoRoot "frontend\src\renderer\src\types\generated\openapi.json"

Push-Location $repoRoot
try {
    & $python -m backend.api.openapi_export $schemaPath
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI export failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Push-Location (Join-Path $repoRoot "frontend")
try {
    npm run gen:api:types
    if ($LASTEXITCODE -ne 0) { throw "openapi-typescript failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "Contracts regenerated." -ForegroundColor Green
