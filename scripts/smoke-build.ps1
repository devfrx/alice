# ─────────────────────────────────────────────────────────────────
# AL\CE — Smoke test for the packaged backend
# ─────────────────────────────────────────────────────────────────
# Launches the frozen backend.exe from frontend/resources/backend/,
# waits a few seconds, hits /api/health, and confirms the response.
# Exits non-zero on any failure so the script can be wired into CI.
#
# Usage:
#   .\scripts\smoke-build.ps1                     # uses staged backend
#   .\scripts\smoke-build.ps1 -ExePath C:\...\backend.exe
#   .\scripts\smoke-build.ps1 -Port 8123
# ─────────────────────────────────────────────────────────────────

[CmdletBinding()]
param(
    [string]$ExePath,
    [int]$Port = 8000,
    [int]$StartupTimeoutSec = 60
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir

if (-not $ExePath) {
    $candidates = @(
        Join-Path $Root "frontend\resources\backend\backend.exe",
        Join-Path $Root "backend\dist\backend\backend.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $ExePath = $c; break }
    }
}

if (-not $ExePath -or -not (Test-Path $ExePath)) {
    Write-Host "  [X] backend.exe not found — run scripts\build-installer.ps1 first." -ForegroundColor Red
    Write-Host "      Tried: $($candidates -join ', ')" -ForegroundColor DarkGray
    exit 1
}

Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  AL\CE — packaged backend smoke test" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  ExePath : $ExePath"
Write-Host "  Port    : $Port"
Write-Host ""

# ─── 1. Launch backend ──────────────────────────────────────────
Write-Host "  → spawning backend.exe --host 127.0.0.1 --port $Port" -ForegroundColor Yellow
$proc = Start-Process -FilePath $ExePath `
    -ArgumentList @("--host", "127.0.0.1", "--port", "$Port") `
    -PassThru `
    -WindowStyle Hidden

if (-not $proc) {
    Write-Host "  [X] Failed to start backend." -ForegroundColor Red
    exit 1
}
Write-Host "  → PID $($proc.Id)" -ForegroundColor DarkGray

$exitCode = 1
try {
    # ─── 2. Poll /api/health ────────────────────────────────────
    $healthUrl = "http://127.0.0.1:$Port/api/health"
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSec)
    $ok = $false
    $lastErr = $null
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            throw "backend.exe exited prematurely (code $($proc.ExitCode))"
        }
        try {
            $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $body = $resp.Content
                Write-Host "  ✓ /api/health → 200 $body" -ForegroundColor Green
                if ($body -notmatch '"status"\s*:\s*"(ok|degraded)"') {
                    throw "unexpected /health payload: $body"
                }
                $ok = $true
                break
            }
        } catch {
            $lastErr = $_
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ok) {
        throw "Timed out after ${StartupTimeoutSec}s waiting for $healthUrl ($lastErr)"
    }
    $exitCode = 0
} catch {
    Write-Host "  [X] $_" -ForegroundColor Red
} finally {
    # ─── 3. Tear down ───────────────────────────────────────────
    if (-not $proc.HasExited) {
        Write-Host "  → stopping backend (PID $($proc.Id))" -ForegroundColor DarkGray
        try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {}
        $proc.WaitForExit(5000) | Out-Null
    }
    # Also kill any orphaned child processes (uvicorn workers).
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.Id)" -ErrorAction SilentlyContinue |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
}

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "  ✓ Smoke test PASSED" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  ✗ Smoke test FAILED" -ForegroundColor Red
}
exit $exitCode
