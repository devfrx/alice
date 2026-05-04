# ─────────────────────────────────────────────────────────────────
# AL\CE — Build Windows Installer (NSIS) — Stream D Phase 1
# ─────────────────────────────────────────────────────────────────
# End-to-end packaging pipeline:
#   1. Build the Vue/Electron frontend bundle (electron-vite).
#   2. Freeze the Python backend with PyInstaller (--onedir).
#   3. Stage the frozen backend under frontend/resources/backend/ so
#      electron-builder picks it up as ``extraResources``.
#   4. Run electron-builder --win nsis → produces
#      frontend/dist-installer/Alice-Setup-<version>.exe.
#
# Usage:
#   .\scripts\build-installer.ps1
#   .\scripts\build-installer.ps1 -SkipFrontendInstall
#   .\scripts\build-installer.ps1 -SkipBackendInstall
#   .\scripts\build-installer.ps1 -DryRun     # electron-builder --dir only
#
# Idempotent: stale intermediates (backend/dist, backend/build,
# frontend/resources/backend, frontend/out, frontend/dist-installer) are
# wiped before each step so repeated runs produce identical artefacts.
# ─────────────────────────────────────────────────────────────────

[CmdletBinding()]
param(
    [switch]$SkipFrontendInstall,
    [switch]$SkipBackendInstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Native CLIs (npm / npx / uv / pyinstaller) routinely write progress and
# warnings to stderr.  Under the default 'Stop' preference, redirecting
# those streams (e.g. ``script *> log.txt``) promotes every stderr line to
# a terminating PowerShell error.  Keep error handling driven by
# ``$LASTEXITCODE`` checks instead so warnings cannot abort the pipeline.
$PSNativeCommandUseErrorActionPreference = $false

# ─── Paths ──────────────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root        = Split-Path -Parent $ScriptDir
$Frontend    = Join-Path $Root "frontend"
$Backend     = Join-Path $Root "backend"
$BackendDist = Join-Path $Backend "dist\backend"
$BackendBuild = Join-Path $Backend "build"
$Stage       = Join-Path $Frontend "resources\backend"
$Installer   = Join-Path $Frontend "dist-installer"
$RendererOut = Join-Path $Frontend "out"

# Default voice models pre-bundled in the installer so STT/TTS work
# out-of-the-box.  Users can download additional models from the in-app
# Service Status panel (Phase 1 finalisation).
$DefaultModels = @(
    @{ url = 'https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin'; rel = 'stt\faster-whisper-small\model.bin' },
    @{ url = 'https://huggingface.co/Systran/faster-whisper-small/resolve/main/config.json'; rel = 'stt\faster-whisper-small\config.json' },
    @{ url = 'https://huggingface.co/Systran/faster-whisper-small/resolve/main/tokenizer.json'; rel = 'stt\faster-whisper-small\tokenizer.json' },
    @{ url = 'https://huggingface.co/Systran/faster-whisper-small/resolve/main/vocabulary.txt'; rel = 'stt\faster-whisper-small\vocabulary.txt' },
    @{ url = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx'; rel = 'tts\piper\it_IT-paola-medium.onnx' },
    @{ url = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json'; rel = 'tts\piper\it_IT-paola-medium.onnx.json' }
)

function Write-Step {
    param([int]$Step, [int]$Total, [string]$Msg)
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  [$Step/$Total] $Msg" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
}

function Stop-LockingProcesses {
    <#
    .SYNOPSIS
        Terminate processes known to lock files inside backend/dist or
        the Electron stage so the next build can wipe them cleanly.
    .DESCRIPTION
        PyInstaller's onedir output (e.g. _internal\av\*.pyd) and Electron
        binaries (Alice.exe / backend.exe) keep file handles open while
        running.  A stale process from a previous run — or the installed
        app — will make Remove-Item fail with "Access denied".
        We kill them by name before cleaning; safe no-op when none exist.
    #>
    $names = @('backend', 'Alice', 'electron', 'pyinstaller')
    foreach ($n in $names) {
        Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "  → killing locking process: $($_.ProcessName) (PID $($_.Id))" -ForegroundColor DarkYellow
            try { $_ | Stop-Process -Force -ErrorAction Stop } catch {
                Write-Host "    (could not stop $($_.Id): $($_.Exception.Message))" -ForegroundColor DarkGray
            }
        }
    }
}

function Remove-IfExists {
    <#
    .SYNOPSIS
        Recursively delete $Path with retries so transient AV/handle
        locks (Defender scanning a freshly-written .pyd, etc.) do not
        abort the pipeline.
    #>
    param(
        [string]$Path,
        [int]$MaxAttempts = 5
    )
    if (-not (Test-Path $Path)) { return }
    Write-Host "  → cleaning $Path" -ForegroundColor DarkGray
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq 1) {
                # First failure: kill known locking processes once.
                Stop-LockingProcesses
            }
            if ($i -eq $MaxAttempts) {
                throw "Failed to remove '$Path' after $MaxAttempts attempts: $($_.Exception.Message)"
            }
            Write-Host "    retry $i/$MaxAttempts after lock: $($_.Exception.Message)" -ForegroundColor DarkGray
            Start-Sleep -Milliseconds (500 * $i)
        }
    }
}

# ─── Pre-flight ─────────────────────────────────────────────────
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  AL\CE — Installer build pipeline" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Root        : $Root"
Write-Host "  Backend     : $Backend"
Write-Host "  Frontend    : $Frontend"
Write-Host "  Stage dir   : $Stage"
Write-Host "  Output dir  : $Installer"
Write-Host "  DryRun      : $DryRun"
Write-Host ""

foreach ($cmd in @('node', 'npm', 'uv')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "  [X] '$cmd' not found in PATH — aborting." -ForegroundColor Red
        exit 1
    }
}

# Pre-emptively close any AL\CE / backend.exe / Electron process that
# could still hold handles into our build outputs from a prior run or
# the installed app.  Without this, the first Remove-Item in step 2
# fails with "Access denied" on _internal\av\*.pyd.
Stop-LockingProcesses

# ─── 1. Frontend build ──────────────────────────────────────────
Write-Step 1 6 "Frontend — electron-vite build"
Push-Location $Frontend
try {
    Remove-IfExists $RendererOut
    if (-not $SkipFrontendInstall) {
        Write-Host "  → npm ci" -ForegroundColor Yellow
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit $LASTEXITCODE)" }
    } else {
        Write-Host "  → skipping npm ci (-SkipFrontendInstall)" -ForegroundColor DarkYellow
    }
    Write-Host "  → npx electron-vite build (typecheck skipped — owned by Streams A/B/C)" -ForegroundColor Yellow
    npx electron-vite build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# ─── 2. Backend freeze ──────────────────────────────────────────
Write-Step 2 6 "Backend — PyInstaller freeze (onedir)"
Push-Location $Backend
try {
    Remove-IfExists $BackendDist
    Remove-IfExists $BackendBuild
    $py = Join-Path $Backend ".venv\Scripts\python.exe"
    if (-not $SkipBackendInstall) {
        Write-Host "  → uv sync --extra dev --extra voice" -ForegroundColor Yellow
        # An outer activation can leave VIRTUAL_ENV pointing at a sibling
        # venv (e.g. alice\.venv), which makes ``uv pip install`` target
        # the wrong interpreter.  Scope both commands to the backend's
        # own project environment to keep PyInstaller installed where
        # we will invoke it from below.
        $prevVenv = $env:VIRTUAL_ENV
        $env:VIRTUAL_ENV = $null
        try {
            uv sync --extra dev --extra voice
            if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)" }
            if (-not (Test-Path $py)) {
                throw "Python interpreter not found at $py after uv sync."
            }
            Write-Host "  → uv pip install --python `"$py`" pyinstaller" -ForegroundColor Yellow
            uv pip install --python "$py" pyinstaller
            if ($LASTEXITCODE -ne 0) { throw "pyinstaller install failed (exit $LASTEXITCODE)" }
        } finally {
            $env:VIRTUAL_ENV = $prevVenv
        }
    } else {
        Write-Host "  → skipping uv sync / pyinstaller install (-SkipBackendInstall)" -ForegroundColor DarkYellow
    }
    if (-not (Test-Path $py)) {
        throw "Python interpreter not found at $py — run setup.ps1 first."
    }
    Write-Host "  → pyinstaller backend.spec --noconfirm --clean" -ForegroundColor Yellow
    & $py -m PyInstaller backend.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed (exit $LASTEXITCODE)" }
    if (-not (Test-Path (Join-Path $BackendDist "backend.exe"))) {
        throw "PyInstaller did not produce backend.exe at $BackendDist"
    }
} finally {
    Pop-Location
}

# ─── 3. Stage backend under frontend/resources/backend/ ─────────
Write-Step 3 6 "Stage frozen backend → frontend/resources/backend"
Remove-IfExists $Stage
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
# Copy contents of dist\backend (not the directory itself) so
# extraResources points at .../resources/backend/{backend.exe,_internal/...}.
Copy-Item -Path (Join-Path $BackendDist "*") -Destination $Stage -Recurse -Force

# Bundle Trellis launchers so the in-app Start button can spawn them
# without requiring a separate clone of the AL\CE repository.
$ScriptsStage = Join-Path $Stage "scripts"
New-Item -ItemType Directory -Force -Path $ScriptsStage | Out-Null
foreach ($launcher in @('start-trellis2.ps1', 'start-trellis.ps1')) {
    $src = Join-Path $Root "scripts\$launcher"
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $ScriptsStage -Force
        Write-Host "  → bundled $launcher" -ForegroundColor DarkGray
    }
}
foreach ($serverDir in @('trellis_server', 'trellis2_server')) {
    $src = Join-Path $Root $serverDir
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $Stage $serverDir) -Recurse -Force
        Write-Host "  → bundled $serverDir" -ForegroundColor DarkGray
    }
}
Write-Host "  → staged $((Get-ChildItem $Stage -Recurse | Measure-Object).Count) files" -ForegroundColor Green

# ─── 4. Pre-download default voice models ───────────────────────
Write-Step 4 6 "Pre-download default voice models (whisper-small + piper IT)"
$ModelsStage = Join-Path $Stage "models"
New-Item -ItemType Directory -Force -Path $ModelsStage | Out-Null

# ``Invoke-WebRequest`` is unusably slow when ``$ProgressPreference`` is
# ``Continue`` (it repaints the console for every chunk, capping throughput
# at ~1-2 MB/s).  Suppress it for the whole step so the 475 MB whisper
# model.bin downloads at line speed.  We also fan out the file list across
# parallel jobs because HuggingFace's CDN throttles single-stream downloads
# but happily serves multiple connections in parallel.
$prevProgress = $ProgressPreference
$ProgressPreference = 'SilentlyContinue'

# PS 5.1 defaults to TLS 1.0/1.1 which both PSGallery and HuggingFace
# reject.  Enable TLS 1.2 process-wide so Install-Module and HttpClient
# both succeed without surprises.  No-op on PS 7+ (already on TLS 1.2+).
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    # Older .NET frameworks may not know the Tls12 enum value; ignore.
}

# Pick the fastest job primitive available on the host:
#   * ThreadJob — in-process, low overhead (PS 7+ built-in; PS 5.1 via
#     `Install-Module ThreadJob`).  Best throughput.
#   * Start-Job — fallback to out-of-process jobs (heavier but ships
#     with every PowerShell).
$jobCmd = $null
if (Get-Command Start-ThreadJob -ErrorAction SilentlyContinue) {
    $jobCmd = 'Start-ThreadJob'
} else {
    try {
        Import-Module ThreadJob -ErrorAction Stop
        $jobCmd = 'Start-ThreadJob'
    } catch {
        try {
            Write-Host "  → installing ThreadJob module (CurrentUser)…" -ForegroundColor DarkYellow
            # Mark PSGallery trusted so -Force can install non-interactively.
            $repo = Get-PSRepository -Name PSGallery -ErrorAction SilentlyContinue
            if ($repo -and $repo.InstallationPolicy -ne 'Trusted') {
                Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction SilentlyContinue
            }
            Install-Module -Name ThreadJob -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop
            Import-Module ThreadJob -ErrorAction Stop
            $jobCmd = 'Start-ThreadJob'
        } catch {
            Write-Host "  → ThreadJob unavailable ($($_.Exception.Message)), falling back to Start-Job (slower startup)" -ForegroundColor DarkYellow
            $jobCmd = 'Start-Job'
        }
    }
}

# The download body is identical for both ThreadJob and Start-Job.
$downloadScript = {
    param($url, $dest)
    $ProgressPreference = 'SilentlyContinue'
    # Job runspaces (ThreadJob) and child processes (Start-Job) inherit
    # the default TLS protocols from .NET, not from the caller — set
    # TLS 1.2 explicitly or HuggingFace closes the connection.
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromMinutes(15)
    try {
        $response = $client.GetAsync(
            $url,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $fs = [System.IO.File]::Create($dest)
        try {
            $stream.CopyTo($fs, 1MB)
        } finally {
            $fs.Dispose()
            $stream.Dispose()
            $response.Dispose()
        }
    } finally {
        $client.Dispose()
    }
}

try {
    $jobs = @()
    foreach ($entry in $DefaultModels) {
        $target = Join-Path $ModelsStage $entry.rel
        $targetDir = Split-Path -Parent $target
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        if (Test-Path $target) {
            Write-Host "  → already present: $($entry.rel)" -ForegroundColor DarkGray
            continue
        }
        Write-Host "  → queuing $($entry.rel)" -ForegroundColor Yellow
        $jobs += & $jobCmd -Name ("dl-" + $entry.rel) `
            -ScriptBlock $downloadScript `
            -ArgumentList $entry.url, $target
    }

    if ($jobs.Count -gt 0) {
        Write-Host "  → downloading $($jobs.Count) file(s) in parallel via $jobCmd…" -ForegroundColor Yellow
        $jobs | Wait-Job | Out-Null
        $failed = @()
        foreach ($job in $jobs) {
            if ($job.State -ne 'Completed') {
                $failed += "$($job.Name) ($($job.State))"
            }
            # Drain any stderr/output to surface the underlying error message.
            try {
                Receive-Job -Job $job -ErrorAction Stop | Out-Null
            } catch {
                $failed += "$($job.Name): $($_.Exception.Message)"
            }
            Remove-Job -Job $job -Force | Out-Null
        }
        if ($failed.Count -gt 0) {
            throw "Parallel download failed for: $($failed -join '; ')"
        }
    }
} finally {
    $ProgressPreference = $prevProgress
}
$totalSize = (Get-ChildItem $ModelsStage -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host "  → models bundle: $([math]::Round($totalSize / 1MB, 1)) MB" -ForegroundColor Green

# ─── 5. electron-builder ────────────────────────────────────────
Write-Step 5 6 "electron-builder — Windows NSIS installer"

# Pre-populate the winCodeSign cache.  electron-builder ships a 7z
# archive that contains symlinks for darwin .dylib files; on Windows
# without Developer Mode (or admin) 7za fails with
# "Il privilegio richiesto non appartiene al client", which makes
# electron-builder loop forever re-downloading.  Extracting the
# archive ourselves while excluding the darwin symlink targets
# leaves a populated cache so electron-builder skips its own
# extraction.
function Initialize-WinCodeSignCache {
    $cacheRoot = Join-Path $env:LOCALAPPDATA 'electron-builder\Cache\winCodeSign'
    $extracted = Join-Path $cacheRoot 'winCodeSign-2.6.0'
    if (Test-Path (Join-Path $extracted 'windows-10\x64\signtool.exe')) {
        Write-Host "  → winCodeSign cache already populated" -ForegroundColor DarkGray
        return
    }
    New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null
    $sevenZip = Join-Path $Frontend 'node_modules\7zip-bin\win\x64\7za.exe'
    if (-not (Test-Path $sevenZip)) {
        Write-Host "  ! 7za.exe not found at $sevenZip — skipping cache priming" -ForegroundColor DarkYellow
        return
    }
    $archive = Join-Path $cacheRoot 'winCodeSign-2.6.0.7z'
    $url     = 'https://github.com/electron-userland/electron-builder-binaries/releases/download/winCodeSign-2.6.0/winCodeSign-2.6.0.7z'
    Write-Host "  → priming winCodeSign cache (download + safe extract)" -ForegroundColor Yellow
    $prev = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    } finally {
        $ProgressPreference = $prev
    }
    # Exclude the darwin symlink files that trip Windows ACLs.
    & $sevenZip x $archive "-o$extracted" '-aoa' '-bso0' '-bsp0' '-x!darwin' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "winCodeSign pre-extraction failed (exit $LASTEXITCODE)"
    }
    Remove-Item $archive -Force -ErrorAction SilentlyContinue
}
Initialize-WinCodeSignCache

Push-Location $Frontend
try {
    Remove-IfExists $Installer
    if ($DryRun) {
        Write-Host "  → npx electron-builder --dir (dry run, no installer)" -ForegroundColor Yellow
        npx electron-builder --dir
    } else {
        Write-Host "  → npx electron-builder --win nsis" -ForegroundColor Yellow
        npx electron-builder --win nsis
    }
    if ($LASTEXITCODE -ne 0) { throw "electron-builder failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# ─── 5. Report ──────────────────────────────────────────────────
Write-Step 6 6 "Done"
if ($DryRun) {
    $unpacked = Get-ChildItem -Path $Installer -Directory -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($unpacked) {
        Write-Host "  ✓ Unpacked app: $($unpacked.FullName)" -ForegroundColor Green
    } else {
        Write-Host "  ! Dry-run produced no output under $Installer" -ForegroundColor Yellow
    }
} else {
    $setup = Get-ChildItem -Path $Installer -Filter "*.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($setup) {
        Write-Host "  ✓ Installer: $($setup.FullName)" -ForegroundColor Green
        Write-Host "  ✓ Size     : $([math]::Round($setup.Length / 1MB, 1)) MB" -ForegroundColor Green
    } else {
        Write-Host "  ! No installer found under $Installer" -ForegroundColor Yellow
        exit 1
    }
}
