# ──────────────────────────────────────────────────
# O.M.N.I.A. — Full Setup Script (Windows)
# ──────────────────────────────────────────────────
# Run from project root:  .\scripts\setup.ps1
#
# Flags:
#   -CpuOnly        Skip NVIDIA/CUDA packages (use CPU for STT)
#   -SkipModels     Skip downloading Piper TTS voice model
#   -SkipFrontend   Skip npm install
#   -SkipOllama     Skip Ollama install + model pull

param(
    [switch]$CpuOnly,
    [switch]$SkipModels,
    [switch]$SkipFrontend,
    [switch]$SkipOllama
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host ""
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  O.M.N.I.A. — Full Setup" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$steps = 7
if ($SkipFrontend) { $steps-- }
if ($SkipOllama)   { $steps-- }
if ($SkipModels)   { $steps-- }
$step = 0

# ── 1. Check prerequisites ──────────────────────
$step++
Write-Host "[$step/$steps] Checking prerequisites..." -ForegroundColor Yellow

# Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "  ✗ Python not found. Install Python 3.11+ from python.org" -ForegroundColor Red
    exit 1
}
$pyVersion = python --version 2>&1
Write-Host "  ✓ $pyVersion" -ForegroundColor Green

# Node
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "  ✗ Node.js not found. Install from nodejs.org" -ForegroundColor Red
    exit 1
}
$nodeVersion = node --version 2>&1
Write-Host "  ✓ Node.js $nodeVersion" -ForegroundColor Green

# pip
$pip = & "$Root\backend\.venv\Scripts\python.exe" -m pip --version 2>$null
if (-not $pip -and -not (Test-Path "$Root\backend\.venv")) {
    Write-Host "  → No venv found, will create one" -ForegroundColor Yellow
}

# ── 2. Create directories ───────────────────────
$step++
Write-Host ""
Write-Host "[$step/$steps] Creating directories..." -ForegroundColor Yellow

$dirs = @(
    "$Root\data\conversations",
    "$Root\data\uploads",
    "$Root\models\stt",
    "$Root\models\tts",
    "$Root\models\llm"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Path $d -Force | Out-Null
}
Write-Host "  ✓ Data and model directories ready" -ForegroundColor Green

# ── 3. Backend: venv + core deps ────────────────
$step++
Write-Host ""
Write-Host "[$step/$steps] Setting up Python backend..." -ForegroundColor Yellow

Push-Location "$Root\backend"

# Create venv if missing
if (-not (Test-Path ".venv")) {
    Write-Host "  → Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

$pip_exe = "$Root\backend\.venv\Scripts\python.exe"

# Core + dev dependencies
Write-Host "  → Installing core + dev dependencies..." -ForegroundColor Yellow
& $pip_exe -m pip install -e ".[dev]" --quiet 2>$null

# Voice dependencies (STT + TTS + VRAM)
if ($CpuOnly) {
    Write-Host "  → Installing voice packages (CPU mode)..." -ForegroundColor Yellow
    & $pip_exe -m pip install -e ".[voice]" --quiet 2>$null
} else {
    Write-Host "  → Installing voice packages (GPU + CUDA)..." -ForegroundColor Yellow
    & $pip_exe -m pip install -e ".[voice-gpu]" --quiet 2>$null
}

# File reader (PDF, DOCX)
Write-Host "  → Installing file-reader packages..." -ForegroundColor Yellow
& $pip_exe -m pip install -e ".[file-reader]" --quiet 2>$null

# Add project root to Python path so 'from backend.X' imports resolve.
$siteDir = & $pip_exe -c "import sysconfig; print(sysconfig.get_path('purelib'))"
$Root | Out-File -FilePath "$siteDir\omnia_root.pth" -Encoding ASCII -NoNewline

Pop-Location
Write-Host "  ✓ Backend ready (core + voice + file-reader)" -ForegroundColor Green

# ── 4. Download Piper TTS voice model ───────────
if (-not $SkipModels) {
    $step++
    Write-Host ""
    Write-Host "[$step/$steps] Downloading Piper TTS voice model..." -ForegroundColor Yellow

    $ttsDir  = "$Root\models\tts"
    $onnx    = "$ttsDir\it_IT-paola-medium.onnx"
    $json    = "$ttsDir\it_IT-paola-medium.onnx.json"
    $baseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/it/it_IT/paola/medium"

    if (-not (Test-Path $onnx)) {
        Write-Host "  → Downloading it_IT-paola-medium.onnx (~65 MB)..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri "$baseUrl/it_IT-paola-medium.onnx" -OutFile $onnx
    } else {
        Write-Host "  ✓ it_IT-paola-medium.onnx already present" -ForegroundColor Green
    }

    if (-not (Test-Path $json)) {
        Write-Host "  → Downloading it_IT-paola-medium.onnx.json..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri "$baseUrl/it_IT-paola-medium.onnx.json" -OutFile $json
    } else {
        Write-Host "  ✓ it_IT-paola-medium.onnx.json already present" -ForegroundColor Green
    }

    Write-Host "  ✓ Piper voice model ready" -ForegroundColor Green
}

# ── 5. Frontend setup ───────────────────────────
if (-not $SkipFrontend) {
    $step++
    Write-Host ""
    Write-Host "[$step/$steps] Setting up Electron frontend..." -ForegroundColor Yellow

    Push-Location "$Root\frontend"
    npm install --silent 2>$null
    Pop-Location
    Write-Host "  ✓ Frontend dependencies installed" -ForegroundColor Green
}

# ── 6. Ollama (optional LLM provider) ──────────
if (-not $SkipOllama) {
    $step++
    Write-Host ""
    Write-Host "[$step/$steps] Checking Ollama..." -ForegroundColor Yellow

    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        Write-Host "  → Installing Ollama via winget..." -ForegroundColor Yellow
        winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements
    }
    Write-Host "  ✓ Ollama installed" -ForegroundColor Green
}

# ── 7. Verify installation ──────────────────────
$step++
Write-Host ""
Write-Host "[$step/$steps] Verifying installation..." -ForegroundColor Yellow

$pip_exe = "$Root\backend\.venv\Scripts\python.exe"
$checks = @(
    @{ Name = "FastAPI";         Cmd = "import fastapi" },
    @{ Name = "faster-whisper";  Cmd = "import faster_whisper" },
    @{ Name = "piper-tts";      Cmd = "import piper" },
    @{ Name = "kokoro-onnx";    Cmd = "import kokoro_onnx" },
    @{ Name = "pynvml";         Cmd = "import pynvml" },
    @{ Name = "pdfplumber";     Cmd = "import pdfplumber" },
    @{ Name = "python-docx";    Cmd = "import docx" }
)

if (-not $CpuOnly) {
    $checks += @{ Name = "nvidia-cublas-cu12"; Cmd = "import nvidia.cublas" }
    $checks += @{ Name = "nvidia-cudnn-cu12";  Cmd = "import nvidia.cudnn" }
}

$allOk = $true
foreach ($check in $checks) {
    $result = & $pip_exe -c $check.Cmd 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ $($check.Name)" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $($check.Name) — MISSING" -ForegroundColor Red
        $allOk = $false
    }
}

# Check Piper model files
$onnxOk = Test-Path "$Root\models\tts\it_IT-paola-medium.onnx"
$jsonOk = Test-Path "$Root\models\tts\it_IT-paola-medium.onnx.json"
if ($onnxOk -and $jsonOk) {
    Write-Host "  ✓ Piper voice model" -ForegroundColor Green
} else {
    Write-Host "  ✗ Piper voice model — files missing in models/tts/" -ForegroundColor Red
    $allOk = $false
}

# ── Done ────────────────────────────────────────
Write-Host ""
if ($allOk) {
    Write-Host "═══════════════════════════════════════" -ForegroundColor Green
    Write-Host "  O.M.N.I.A. setup complete!" -ForegroundColor Green
    Write-Host "═══════════════════════════════════════" -ForegroundColor Green
} else {
    Write-Host "═══════════════════════════════════════" -ForegroundColor Yellow
    Write-Host "  Setup finished with warnings" -ForegroundColor Yellow
    Write-Host "  Check the ✗ items above" -ForegroundColor Yellow
    Write-Host "═══════════════════════════════════════" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Start dev:  .\scripts\start-dev.ps1" -ForegroundColor Cyan
Write-Host ""
