# ------------------------------------------------
# AL\CE - Start TRELLIS 3D Microservice
# ------------------------------------------------
# Run: .\scripts\start-trellis.ps1
#
# Starts the TRELLIS microservice (port 8090) using the TRELLIS-for-windows
# Python 3.10 venv.  Pass -Install to run the one-time installation first.
#
# Examples:
#   .\scripts\start-trellis.ps1                          # just start
#   .\scripts\start-trellis.ps1 -Install                 # install + start
#   .\scripts\start-trellis.ps1 -Model JeffreyXiang/TRELLIS-text-base # lighter model

param(
    [switch]$Install,
    [string]$Model = "",
    [int]$Port = 8090,
    [string]$TrellisDir = "",
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

# -- Resolve paths --
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$AliceRoot     = Split-Path -Parent $ScriptDir
$WorkspaceRoot = Split-Path -Parent $AliceRoot
if (-not $TrellisDir) { $TrellisDir = Join-Path $WorkspaceRoot "TRELLIS-for-windows" }
$TrellisDir    = [IO.Path]::GetFullPath($TrellisDir)
$ServerPy      = Join-Path $AliceRoot "trellis_server\server.py"

Write-Host ""
Write-Host "=======================================" -ForegroundColor Magenta
Write-Host "  AL\CE - TRELLIS 3D Service" -ForegroundColor Magenta
Write-Host "=======================================" -ForegroundColor Magenta
Write-Host ""

# -- Check TRELLIS-for-windows exists --
if (-not (Test-Path $TrellisDir)) {
    Write-Host "  [X] TRELLIS-for-windows not found at:" -ForegroundColor Red
    Write-Host "      $TrellisDir" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Clone it with:" -ForegroundColor Yellow
    Write-Host "    git clone --recurse-submodules https://github.com/devfrx/TRELLIS-for-windows.git `"$TrellisDir`"" -ForegroundColor Cyan
    exit 1
}

# -- Install mode --
if ($Install) {
    Write-Host "  -> Running TRELLIS installation..." -ForegroundColor Yellow
    Write-Host "     (this may take 20-30 minutes)" -ForegroundColor DarkGray
    Write-Host ""

    # Find the install script dynamically (filename contains Chinese characters)
    $installScript = Get-ChildItem $TrellisDir -Filter "1*install-uv-qinglong.ps1" |
        Where-Object { $_.Name -notmatch "manual" } |
        Select-Object -First 1
    if (-not $installScript) {
        Write-Host "  [X] Install script not found in $TrellisDir" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Running: $($installScript.Name)" -ForegroundColor DarkGray
    Push-Location $TrellisDir
    try {
        & powershell -ExecutionPolicy Bypass -File $installScript.FullName
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Write-Host "  [X] Installation failed (exit code $LASTEXITCODE)" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Host ""
    Write-Host "  [OK] TRELLIS installation complete" -ForegroundColor Green
    Write-Host ""
}

# -- Check .venv exists --
$VenvPython = Join-Path $TrellisDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "  [X] TRELLIS .venv not found - run installation first:" -ForegroundColor Red
    Write-Host "      .\scripts\start-trellis.ps1 -Install" -ForegroundColor Cyan
    exit 1
}

# -- Check server.py exists --
if (-not (Test-Path $ServerPy)) {
    Write-Host "  [X] server.py not found at: $ServerPy" -ForegroundColor Red
    exit 1
}

# -- Read model from config if not specified --
if (-not $Model) {
    $ConfigPath = Join-Path $AliceRoot "config\default.yaml"
    if (Test-Path $ConfigPath) {
        $match = Select-String -Path $ConfigPath -Pattern '^\s*trellis_model:\s*"?([^"#]+)"?' | Select-Object -First 1
        if ($match) {
            $Model = $match.Matches[0].Groups[1].Value.Trim().Trim('"')
        }
    }
    if (-not $Model) { $Model = "JeffreyXiang/TRELLIS-text-large" }
}

# -- Check if port is already in use --
# Filter out TIME_WAIT / CLOSE_WAIT connections (PID=0 = kernel, not a real server)
$portInUse = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" -or ($_.OwningProcess -gt 0 -and $_.State -eq "Established") }
if ($portInUse) {
    # NOTE: $pid is a PowerShell automatic variable (current shell PID) and is
    # read-only — assigning to it raises an error. Use $procId instead.
    $procId = $portInUse[0].OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "  [!] Port $Port already in use - TRELLIS might be running" -ForegroundColor Yellow
    Write-Host "      PID: $procId  ($($proc.ProcessName))" -ForegroundColor DarkGray
    Write-Host ""
    if ($NoPrompt) { exit 0 }
    $answer = Read-Host "  Continue anyway? (y/N)"
    if ($answer -ne "y" -and $answer -ne "Y") { exit 0 }
}

# -- Start the microservice --
$OutputDir = Join-Path $AliceRoot "data\3d_models"
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "  Model:      $Model" -ForegroundColor Cyan
Write-Host "  Port:       $Port" -ForegroundColor Cyan
Write-Host "  Output dir: $OutputDir" -ForegroundColor Cyan
Write-Host "  Python:     $VenvPython" -ForegroundColor Cyan
Write-Host ""
Write-Host "  -> Starting TRELLIS microservice..." -ForegroundColor Yellow
Write-Host "     (first run downloads model weights from HuggingFace)" -ForegroundColor DarkGray
Write-Host ""

# Pass --trellis-dir so server.py adds TRELLIS-for-windows to sys.path.
# The server can then run from any cwd and still resolve trellis.* imports.
& $VenvPython $ServerPy --model $Model --port $Port --output-dir $OutputDir --trellis-dir $TrellisDir