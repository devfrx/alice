# ------------------------------------------------
# AL\CE - Start TRELLIS.2 3D Microservice
# ------------------------------------------------
# Run: .\scripts\start-trellis2.ps1
#
# Starts the TRELLIS.2 microservice (port 8091) using a Python 3.10 venv
# created inside the TRELLIS.2 directory.  Pass -Install to perform the
# one-time installation first (Windows port of the official setup.sh).
#
# Examples:
#   .\scripts\start-trellis2.ps1                          # just start
#   .\scripts\start-trellis2.ps1 -Install                 # install + start
#   .\scripts\start-trellis2.ps1 -Port 8091
#
# Notes
# -----
# TRELLIS.2 is officially Linux-only.  This script attempts the same
# install steps as setup.sh on Windows using uv + pip.  Several CUDA
# extensions (flash-attn, nvdiffrast, nvdiffrec, CuMesh, FlexGEMM,
# o-voxel) compile from source against your local CUDA toolkit and
# Visual Studio Build Tools — see docs/trellis2-setup.md for details.

param(
    [switch]$Install,
    [string]$Model = "",
    [int]$Port = 8091
)

$ErrorActionPreference = "Stop"

# -- Resolve paths --
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$AliceRoot     = Split-Path -Parent $ScriptDir
$WorkspaceRoot = Split-Path -Parent $AliceRoot
$Trellis2Dir   = Join-Path $WorkspaceRoot "TRELLIS.2"
$ServerPy      = Join-Path $AliceRoot "trellis2_server\server.py"

Write-Host ""
Write-Host "=======================================" -ForegroundColor Magenta
Write-Host "  AL\CE - TRELLIS.2 3D Service" -ForegroundColor Magenta
Write-Host "=======================================" -ForegroundColor Magenta
Write-Host ""

# -- Check TRELLIS.2 exists --
if (-not (Test-Path $Trellis2Dir)) {
    Write-Host "  [X] TRELLIS.2 not found at:" -ForegroundColor Red
    Write-Host "      $Trellis2Dir" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Clone it with:" -ForegroundColor Yellow
    Write-Host "    git clone --recurse-submodules https://github.com/microsoft/TRELLIS.2.git `"$Trellis2Dir`"" -ForegroundColor Cyan
    exit 1
}

# -- Install mode --
if ($Install) {
    Write-Host "  -> Running TRELLIS.2 installation..." -ForegroundColor Yellow
    Write-Host "     (this may take 30-60 minutes; compiles CUDA extensions)" -ForegroundColor DarkGray
    Write-Host ""

    # Pre-flight: uv must be available (used to create the Python 3.10 venv).
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        Write-Host "  [X] 'uv' not found on PATH." -ForegroundColor Red
        Write-Host "      Install with: winget install --id=astral-sh.uv -e" -ForegroundColor Cyan
        exit 1
    }

    # Pre-flight: CUDA_HOME MUST point to CUDA 12.x (NOT 13.x) because the
    # torch wheels we install are compiled for cu128. A mismatched nvcc
    # produces:
    #   RuntimeError: detected CUDA version (13.x) mismatches the version
    #   that was used to compile PyTorch (12.8)
    # when building extensions like nvdiffrast / CuMesh / FlexGEMM / o-voxel.
    # We override any pre-existing CUDA_HOME / CUDA_PATH from the system env.
    $cudaBase = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    $cuda12 = $null
    if (Test-Path $cudaBase) {
        # Prefer 12.8, then any other 12.x; explicitly ignore 13.x.
        $candidates = Get-ChildItem $cudaBase -Directory |
            Where-Object { $_.Name -match '^v12\.[0-9]+$' -and (Test-Path (Join-Path $_.FullName "bin\nvcc.exe")) }
        $cuda12 = $candidates | Where-Object { $_.Name -eq 'v12.8' } | Select-Object -First 1
        if (-not $cuda12) {
            $cuda12 = $candidates | Sort-Object Name -Descending | Select-Object -First 1
        }
    }
    if (-not $cuda12) {
        Write-Host "  [X] CUDA Toolkit 12.x not found (need nvcc.exe)." -ForegroundColor Red
        Write-Host "      Install CUDA 12.8 from https://developer.nvidia.com/cuda-12-8-0-download-archive" -ForegroundColor Cyan
        exit 1
    }
    $env:CUDA_HOME = $cuda12.FullName
    $env:CUDA_PATH = $cuda12.FullName
    Write-Host "  CUDA_HOME forced to: $($cuda12.FullName)" -ForegroundColor DarkGray

    # Strip any other CUDA bin from PATH and prepend the chosen one, so that
    # `nvcc --version` (used by torch._check_cuda_version) always picks 12.x.
    $cudaBin = Join-Path $cuda12.FullName "bin"
    $cudaLibnvvp = Join-Path $cuda12.FullName "libnvvp"
    $cleanPath = ($env:PATH -split [IO.Path]::PathSeparator |
        Where-Object { $_ -and ($_ -notmatch [Regex]::Escape($cudaBase)) }) -join [IO.Path]::PathSeparator
    $env:PATH = $cudaBin + [IO.Path]::PathSeparator + $cudaLibnvvp + [IO.Path]::PathSeparator + $cleanPath

    # Sanity check: which nvcc wins on PATH?
    $nvccCmd = Get-Command nvcc -ErrorAction SilentlyContinue
    if ($nvccCmd) {
        Write-Host "  nvcc on PATH:        $($nvccCmd.Source)" -ForegroundColor DarkGray
    }

    # MSVC (cl.exe) must be on PATH or torch's C++ extension build will fail
    # with: "Error checking compiler version for cl: file not found".
    # We auto-import the VS environment using vswhere + VsDevCmd.bat if cl
    # is not already reachable.
    $clCmd = Get-Command cl.exe -ErrorAction SilentlyContinue
    if (-not $clCmd) {
        Write-Host "  cl.exe not on PATH - importing VS Build Tools env..." -ForegroundColor DarkGray
        $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
        if (Test-Path $vswhere) {
            $vsRoot = & $vswhere -latest -products * `
                -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
                -property installationPath
            if ($vsRoot) {
                $vsDevCmd = Join-Path $vsRoot "Common7\Tools\VsDevCmd.bat"
                if (Test-Path $vsDevCmd) {
                    # Capture the env vars set by VsDevCmd into the current session.
                    $envDump = cmd /c "`"$vsDevCmd`" -arch=x64 -host_arch=x64 >NUL && set"
                    foreach ($line in $envDump) {
                        if ($line -match '^([^=]+)=(.*)$') {
                            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
                        }
                    }
                    # Re-prepend our chosen CUDA bin so VsDevCmd doesn't override it.
                    $env:PATH = $cudaBin + [IO.Path]::PathSeparator + $env:PATH
                    $clCmd = Get-Command cl.exe -ErrorAction SilentlyContinue
                }
            }
        }
        if ($clCmd) {
            Write-Host "  cl.exe on PATH:      $($clCmd.Source)" -ForegroundColor DarkGray
        } else {
            Write-Host "  [!] cl.exe still not found - install VS 2022 Build Tools with 'C++ build tools' workload" -ForegroundColor Yellow
            Write-Host "      https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Cyan
        }
    } else {
        Write-Host "  cl.exe on PATH:      $($clCmd.Source)" -ForegroundColor DarkGray
    }

    # Blackwell (RTX 50xx, sm_120) requires arch 12.0; older cards covered too.
    if (-not $env:TORCH_CUDA_ARCH_LIST) {
        $env:TORCH_CUDA_ARCH_LIST = "8.0;8.6;8.9;9.0;12.0"
    }
    $env:DISTUTILS_USE_SDK = "1"

    Push-Location $Trellis2Dir
    try {
        # 1. Create the venv if missing.
        $VenvPython = Join-Path $Trellis2Dir ".venv\Scripts\python.exe"
        if (-not (Test-Path $VenvPython)) {
            Write-Host "  [1/8] Creating Python 3.10 venv..." -ForegroundColor Yellow
            & uv venv --python 3.10 .venv
            if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
        } else {
            Write-Host "  [1/8] Reusing existing venv at .venv" -ForegroundColor DarkGray
        }

        # All subsequent installs go through `uv pip` against the venv's
        # Python. We avoid `python -m pip` because `uv venv` does NOT
        # bootstrap pip by default (and we don't need it: uv resolves and
        # installs faster than pip for the same wheels).
        function Pip { param([Parameter(ValueFromRemainingArguments)]$args)
            & uv pip install --python $VenvPython @args
            if ($LASTEXITCODE -ne 0) { throw "uv pip install failed: $args" }
        }

        # 2. PyTorch + cu128 (matches existing CUDA 12.8 install + sm_120 Blackwell support).
        # Note: setup.sh upstream uses 2.6.0+cu124, but on Windows with
        # RTX 50xx we need the same cu128 stack already used by TRELLIS classico.
        Write-Host "  [2/8] Installing PyTorch 2.7.0 (cu128)..." -ForegroundColor Yellow
        Pip torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128

        # 3. Basic Python deps (port of setup.sh --basic, minus apt + pillow-simd).
        Write-Host "  [3/8] Installing basic dependencies..." -ForegroundColor Yellow
        Pip imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja `
            trimesh transformers gradio==6.0.1 tensorboard pandas lpips zstandard `
            kornia timm fastapi "uvicorn[standard]" python-multipart pillow
        Pip "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

        # 4. flash-attn (prebuilt wheel where possible).
        Write-Host "  [4/8] Installing flash-attn (cu128/torch2.7 prebuilt wheel)..." -ForegroundColor Yellow
        # Build deps required when using --no-build-isolation (flash-attn
        # imports psutil/packaging/setuptools/wheel during setup.py).
        Pip --upgrade setuptools wheel packaging psutil ninja
        # Prebuilt Windows wheel matching torch 2.7+cu128 (kingbri1 fork,
        # same source already used by TRELLIS classico).
        $flashWheel = "https://github.com/kingbri1/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu128torch2.7.0cxx11abiFALSE-cp310-cp310-win_amd64.whl"
        Write-Host "        downloading prebuilt wheel..." -ForegroundColor DarkGray
        & uv pip install --python $VenvPython $flashWheel
        if ($LASTEXITCODE -ne 0) {
            Write-Host "        prebuilt wheel unavailable - falling back to source build (very slow!)" -ForegroundColor Yellow
            Pip flash-attn==2.7.3 --no-build-isolation
        }

        # 5. nvdiffrast (JIT-compiled at first use).
        Write-Host "  [5/8] Installing nvdiffrast 0.4.0..." -ForegroundColor Yellow
        $extDir = Join-Path $env:TEMP "trellis2_ext"
        New-Item -ItemType Directory -Force -Path $extDir | Out-Null
        $nvd = Join-Path $extDir "nvdiffrast"
        if (-not (Test-Path $nvd)) {
            git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git $nvd
        }
        Pip $nvd --no-build-isolation

        # 6. nvdiffrec (renderutils branch).
        Write-Host "  [6/8] Installing nvdiffrec (renderutils)..." -ForegroundColor Yellow
        $nvdr = Join-Path $extDir "nvdiffrec"
        if (-not (Test-Path $nvdr)) {
            git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git $nvdr
        }
        Pip $nvdr --no-build-isolation

        # 7. CuMesh + FlexGEMM (CUDA C++ extensions).
        Write-Host "  [7/8] Installing CuMesh + FlexGEMM..." -ForegroundColor Yellow
        $cumesh = Join-Path $extDir "CuMesh"
        if (-not (Test-Path $cumesh)) {
            git clone --recursive https://github.com/JeffreyXiang/CuMesh.git $cumesh
        }
        Pip $cumesh --no-build-isolation

        $flexgemm = Join-Path $extDir "FlexGEMM"
        if (-not (Test-Path $flexgemm)) {
            git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git $flexgemm
        }
        # Windows/MSVC patch: nvcc + MSVC require the `template` keyword
        # before `.data_ptr<T>()` when called on a `torch::Tensor` whose
        # type is deduced via `auto` inside a template function. Linux/gcc
        # accepts the implicit form, so upstream FlexGEMM never noticed.
        # We rewrite only the offending lines (idempotent: re-running the
        # patch is a no-op once `template ` has been inserted).
        $flexBadFile = Join-Path $flexgemm "flex_gemm\kernels\cuda\spconv\sparse_neighbor_map.cu"
        if (Test-Path $flexBadFile) {
            $orig = Get-Content -Raw $flexBadFile
            $patched = $orig -replace '(expanded_keys|valid_keys)\.data_ptr<T>\(', '$1.template data_ptr<T>('
            if ($orig -ne $patched) {
                Write-Host "        patching FlexGEMM sparse_neighbor_map.cu (.template data_ptr<T>)..." -ForegroundColor DarkGray
                Set-Content -Path $flexBadFile -Value $patched -NoNewline
            }
        }
        Pip $flexgemm --no-build-isolation

        # 8. o-voxel (vendored inside TRELLIS.2 — installed in place).
        # NOTE: o-voxel's pyproject.toml lists `flex_gemm` and `cumesh` as
        # git URL dependencies. Without `--no-deps`, uv would re-clone them
        # into its own cache (bypassing our patched FlexGEMM source) and the
        # build would fail again with the MSVC `template data_ptr<T>` error.
        # Both deps are already installed by steps 7a/7b, so skip resolution.
        Write-Host "  [8/8] Installing o-voxel..." -ForegroundColor Yellow
        $ovoxel = Join-Path $Trellis2Dir "o-voxel"
        if (-not (Test-Path $ovoxel)) {
            throw "o-voxel directory not found in $Trellis2Dir (was --recurse-submodules used during clone?)"
        }
        # Windows/MSVC patches for o-voxel (Linux/gcc-only valid C++):
        #   a) `1e-6d` / `0.0d` use the GCC `d` literal suffix for double,
        #      which MSVC rejects (C3688). Plain `1e-6` / `0.0` are already
        #      double in standard C++.
        #   b) `torch::zeros({N, C}, ...)` where N/C are `size_t` (uint64)
        #      triggers MSVC narrowing into `IntArrayRef` (int64_t list)
        #      with C2398 in /permissive- mode. Cast operands to int64_t.
        # All patches are idempotent (regex won't re-match after rewrite).
        $patches = @(
            @{ File = "src\convert\flexible_dual_grid.cpp";
               From = '(\d+\.\d+(?:e[+-]?\d+)?|\d+e[+-]?\d+)d\b';
               To   = '$1' },
            @{ File = "src\io\svo.cpp";
               From = '\{(svo|codes)\.size\(\)\}';
               To   = '{(int64_t)$1.size()}' },
            @{ File = "src\io\filter_parent.cpp";
               From = '\{N_leaf,\s*C\}';
               To   = '{(int64_t)N_leaf, (int64_t)C}' },
            @{ File = "src\io\filter_neighbor.cpp";
               From = '\{N,\s*C\}';
               To   = '{(int64_t)N, (int64_t)C}' }
        )
        foreach ($p in $patches) {
            $full = Join-Path $ovoxel $p.File
            if (Test-Path $full) {
                $orig = Get-Content -Raw $full
                $patched = [regex]::Replace($orig, $p.From, $p.To)
                if ($orig -ne $patched) {
                    Write-Host "        patching $($p.File)..." -ForegroundColor DarkGray
                    Set-Content -Path $full -Value $patched -NoNewline
                }
            }
        }
        Pip $ovoxel --no-build-isolation --no-deps
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "  [OK] TRELLIS.2 installation complete" -ForegroundColor Green
    Write-Host ""
}

# -- Check .venv exists --
$VenvPython = Join-Path $Trellis2Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "  [X] TRELLIS.2 .venv not found - run installation first:" -ForegroundColor Red
    Write-Host "      .\scripts\start-trellis2.ps1 -Install" -ForegroundColor Cyan
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
        $match = Select-String -Path $ConfigPath -Pattern '^\s*trellis2_model:\s*"?([^"#]+)"?' | Select-Object -First 1
        if ($match) {
            $Model = $match.Matches[0].Groups[1].Value.Trim().Trim('"')
        }
    }
    if (-not $Model) { $Model = "microsoft/TRELLIS.2-4B" }
}

# -- Check if port is already in use --
$portInUse = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" -or ($_.OwningProcess -gt 0 -and $_.State -eq "Established") }
if ($portInUse) {
    # NOTE: $pid is a PowerShell automatic variable (read-only). Use $procId.
    $procId = $portInUse[0].OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "  [!] Port $Port already in use - TRELLIS.2 might be running" -ForegroundColor Yellow
    Write-Host "      PID: $procId  ($($proc.ProcessName))" -ForegroundColor DarkGray
    Write-Host ""
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

# -- HuggingFace token (required: TRELLIS.2 pulls the gated facebook/dinov3-* repo) --
# Lookup order: process env -> alice/.env -> repo root .env.  Show a clear
# warning + URL when missing so the user can fix it before the first /generate.
if (-not $env:HF_TOKEN) {
    foreach ($envFile in @((Join-Path $AliceRoot ".env"), (Join-Path (Split-Path $AliceRoot -Parent) ".env"))) {
        if (Test-Path $envFile) {
            $line = Select-String -Path $envFile -Pattern '^\s*HF_TOKEN\s*=\s*"?([^"#\r\n]+)"?' | Select-Object -First 1
            if ($line) {
                $env:HF_TOKEN = $line.Matches[0].Groups[1].Value.Trim()
                Write-Host "  HF_TOKEN:   loaded from $envFile" -ForegroundColor DarkGray
                break
            }
        }
    }
}
if ($env:HF_TOKEN) {
    # transformers >=4.38 prefers HF_TOKEN; huggingface_hub still reads the legacy var.
    $env:HUGGING_FACE_HUB_TOKEN = $env:HF_TOKEN
    Write-Host "  HF_TOKEN:   set (HuggingFace authentication enabled)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  [!] HF_TOKEN not set." -ForegroundColor Yellow
    Write-Host "      TRELLIS.2 needs the gated 'facebook/dinov3-vitl16-pretrain-lvd1689m' repo." -ForegroundColor Yellow
    Write-Host "      1) Request access:  https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m" -ForegroundColor Yellow
    Write-Host "      2) Create token:    https://huggingface.co/settings/tokens" -ForegroundColor Yellow
    Write-Host "      3) Add to alice\.env:  HF_TOKEN=hf_xxx" -ForegroundColor Yellow
    Write-Host "         (or run: `$env:HF_TOKEN='hf_xxx'  before this script)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "  -> Starting TRELLIS.2 microservice..." -ForegroundColor Yellow
Write-Host "     (first run downloads ~8GB of weights from HuggingFace)" -ForegroundColor DarkGray
Write-Host ""

# Pass --trellis2-dir so server.py adds TRELLIS.2 to sys.path.
& $VenvPython $ServerPy --model $Model --port $Port --output-dir $OutputDir --trellis2-dir $Trellis2Dir
