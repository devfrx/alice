# ------------------------------------------------
# AL\CE - Start Development Environment
# ------------------------------------------------
# Run: .\scripts\start-dev.ps1
#
# Strategy:
#   - Backend runs in the FOREGROUND of this terminal - full colors + real-time logs
#   - Frontend / Trellis open in separate PowerShell windows
#   - Ctrl+C stops the backend and closes the secondary windows

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Trellis,
    [switch]$Mail
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  AL\CE - Dev Mode" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# -- 0. Resolve backend port (with fallback if 8000 is held by another process) --
function Test-PortFree {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return -not $listeners
}

$BackendPort = 8000
if (-not (Test-PortFree -Port 8000)) {
    $owners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } |
        Sort-Object -Unique
    Write-Host "  [!] Port 8000 already in use by: $($owners -join ', ')" -ForegroundColor Yellow
    $picked = $null
    foreach ($p in 8001..8010) {
        if (Test-PortFree -Port $p) { $picked = $p; break }
    }
    if (-not $picked) {
        Write-Host "  [X] No free port in 8001-8010 — aborting." -ForegroundColor Red
        exit 1
    }
    $BackendPort = $picked
    Write-Host "  [OK] Falling back to port $BackendPort" -ForegroundColor Green
}

# Propagate the resolved port to every downstream consumer via env vars.
# - BACKEND_PORT  : read by any tool that needs the backend URL.
# - VITE_API_BASE_URL : read by Vite (frontend) and Electron main process for CSP.
$BackendBase = "http://localhost:$BackendPort"
$env:BACKEND_PORT = "$BackendPort"
$env:VITE_API_BASE_URL = $BackendBase

# -- 1. Check LM Studio is reachable (optional, non-blocking) --
if (-not $FrontendOnly) {
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:1234/v1/models" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        Write-Host "  [OK] LM Studio running on :1234" -ForegroundColor Green
    } catch {
        Write-Host "  [!] LM Studio not detected on :1234 - start it manually if needed" -ForegroundColor Yellow
    }
}

# -- 2. Load .env.email into current process (before forking anything) --
if ($Mail -and -not $FrontendOnly) {
    $envFile = Join-Path $Root ".env.email"
    if (Test-Path $envFile) {
        $count = 0
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)\s*$') {
                $key = $Matches[1].Trim()
                $val = $Matches[2].Trim()
                # Strip surrounding quotes (single or double)
                if ($val.Length -ge 2 -and (($val[0] -eq '"' -and $val[-1] -eq '"') -or ($val[0] -eq "'" -and $val[-1] -eq "'"))) {
                    $val = $val.Substring(1, $val.Length - 2)
                }
                [System.Environment]::SetEnvironmentVariable($key, $val, 'Process')
                $count++
            }
        }
        Write-Host "  [MAIL] .env.email loaded ($count vars)" -ForegroundColor Green
    } else {
        Write-Host "  [!] .env.email non trovato - email service disabled" -ForegroundColor Red
    }
}

# -- 3. Start Frontend in a separate window --
$secondaryProcs = @()

if (-not $BackendOnly) {
    Write-Host "  -> Starting Electron + Vue dev (new window)..." -ForegroundColor Yellow
    # Inject the resolved backend URL so Vite + Electron main pick up the right port.
    $frontendCmd = "`$env:VITE_API_BASE_URL='$BackendBase'; `$env:BACKEND_PORT='$BackendPort'; Set-Location '$Root\frontend'; npm run dev"
    $frontendProc = Start-Process powershell `
        -ArgumentList "-NoExit", "-Command", $frontendCmd `
        -PassThru
    $secondaryProcs += $frontendProc
    Write-Host "  [OK] Frontend window opened (PID: $($frontendProc.Id))" -ForegroundColor Green
}

# -- 4. Start TRELLIS in a separate window (optional) --
if ($Trellis -and -not $FrontendOnly) {
    $TrellisDir = Join-Path (Split-Path -Parent $Root) "TRELLIS-for-windows"
    $TrellisPython = Join-Path $TrellisDir ".venv\Scripts\python.exe"
    $TrellisServer = Join-Path $Root "trellis_server\server.py"
    $TrellisOutput = Join-Path $Root "data\3d_models"

    if ((Test-Path $TrellisPython) -and (Test-Path $TrellisServer)) {
        Write-Host "  -> Starting TRELLIS 3D microservice (new window)..." -ForegroundColor Yellow
        if (-not (Test-Path $TrellisOutput)) {
            New-Item -ItemType Directory -Path $TrellisOutput -Force | Out-Null
        }
        $trellisCmd = "Set-Location '$TrellisDir'; & '$TrellisPython' '$TrellisServer' --model TRELLIS-text-large --port 8090 --output-dir '$TrellisOutput'"
        $trellisProc = Start-Process powershell `
            -ArgumentList "-NoExit", "-Command", $trellisCmd `
            -PassThru
        $secondaryProcs += $trellisProc
        Write-Host "  [OK] TRELLIS window opened on :8090 (PID: $($trellisProc.Id))" -ForegroundColor Green
    } else {
        Write-Host "  [!] TRELLIS not installed - run: .\scripts\start-trellis.ps1 -Install" -ForegroundColor Yellow
    }
}

# -- Status --
Write-Host ""
Write-Host "=======================================" -ForegroundColor Green
Write-Host "  All services started!" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Backend API:    $BackendBase" -ForegroundColor Cyan
Write-Host "  API Docs:       $BackendBase/docs" -ForegroundColor Cyan
if (-not $FrontendOnly) {
    Write-Host "  Ollama:         http://localhost:11434" -ForegroundColor Cyan
}
if ($Trellis) {
    Write-Host "  TRELLIS 3D:     http://localhost:8090" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "  Press Ctrl+C to stop backend and close secondary windows" -ForegroundColor DarkGray
Write-Host ""

# -- 5. Run backend in foreground (blocks; full color output) --
try {
    if (-not $FrontendOnly) {
        Set-Location $Root
        & "backend\.venv\Scripts\python.exe" -m backend --reload --reload-dir backend --port $BackendPort
    } else {
        # Frontend-only: run npm run dev in this terminal
        Set-Location "$Root\frontend"
        npm run dev
    }
} finally {
    # Kill secondary windows on exit
    if ($secondaryProcs.Count -gt 0) {
        Write-Host ""
        Write-Host "  Stopping secondary services..." -ForegroundColor Yellow
        foreach ($proc in $secondaryProcs) {
            if (-not $proc.HasExited) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Write-Host "  [OK] All services stopped." -ForegroundColor Green
}