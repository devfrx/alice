# ------------------------------------------------
# AL\CE - Start TRELLIS.2 Multi-view 3D Microservice
# ------------------------------------------------
# Run: .\scripts\start-trellis2multiview.ps1
#
# Starts the TRELLIS.2 multi-view microservice (port 8092) using a
# Python 3.10 venv created inside the TRELLIS.2.multiview directory.
# Pass -Install to perform the one-time installation first (Windows port
# of the upstream Linux setup.sh).
#
# Examples:
#   .\scripts\start-trellis2multiview.ps1                   # just start
#   .\scripts\start-trellis2multiview.ps1 -Install          # install + start
#   .\scripts\start-trellis2multiview.ps1 -Port 8092
#
# Notes
# -----
# - The multi-view fork (cpuai/Trellis.2.multiview) ships the same
#   trellis2 / o-voxel layout as TRELLIS.2 itself, so the install steps
#   match start-trellis2.ps1 verbatim (torch + flash-attn + nvdiffrast
#   + nvdiffrec + CuMesh + FlexGEMM + o-voxel).
# - This script intentionally does NOT touch the parallel TRELLIS.2
#   (single-image) install: the two services use independent venvs and
#   independent ports so they can coexist or be enabled one at a time.

param(
    [switch]$Install,
    [string]$Model = "",
    [int]$Port = 8092,
    [string]$Trellis2MultiviewDir = "",
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

# -- Resolve paths --
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$AliceRoot     = Split-Path -Parent $ScriptDir
$WorkspaceRoot = Split-Path -Parent $AliceRoot
if (-not $Trellis2MultiviewDir) {
    $Trellis2MultiviewDir = Join-Path $WorkspaceRoot "TRELLIS.2.multiview"
}
$Trellis2MultiviewDir = [IO.Path]::GetFullPath($Trellis2MultiviewDir)
$ServerPy = Join-Path $AliceRoot "trellis2multiview_server\server.py"

function Patch-BiRefNetRmbg {
    param([string]$Root)

    $file = Join-Path $Root "trellis2\pipelines\rembg\BiRefNet.py"
    if (-not (Test-Path $file)) { return }

    $content = Get-Content -Raw $file
    $patched = $content

    if ($patched -notmatch '_all_tied_weights_keys') {
        $patched = $patched -replace "                # Return empty dict if _tied_weights_keys not defined", "                if hasattr(self, '_all_tied_weights_keys'):`r`n                    return self._all_tied_weights_keys`r`n                # Return empty dict if _tied_weights_keys not defined"
    }
    if ($patched -notmatch '@all_tied_weights_keys\.setter') {
        $patched = $patched -replace "                return \{\}\r?\n            cls\.all_tied_weights_keys = all_tied_weights_keys", "                return {}`r`n`r`n            @all_tied_weights_keys.setter`r`n            def all_tied_weights_keys(self, value):`r`n                self._all_tied_weights_keys = value`r`n`r`n            cls.all_tied_weights_keys = all_tied_weights_keys"
    }

    if ($patched -ne $content) {
        Write-Host "  patching RMBG BiRefNet compatibility shim..." -ForegroundColor DarkGray
        Set-Content -Path $file -Value $patched -NoNewline
    }
}

function Patch-DinoV3FeatureExtractor {
    param([string]$Root)

    # ``transformers`` >= 4.50 wraps the DINOv3 transformer block stack
    # inside ``DINOv3ViTEncoder`` (``self.model.model``); the upstream
    # fork hardcodes ``self.model.layer`` and crashes with
    # ``'DINOv3ViTModel' object has no attribute 'layer'``.  Patch the
    # extractor to support both layouts.
    $file = Join-Path $Root "trellis2\modules\image_feature_extractor.py"
    if (-not (Test-Path $file)) { return }

    $content = Get-Content -Raw $file
    if ($content -match 'layer_stack = self\.model\.model\.layer') { return }

    $needle = "        for i, layer_module in enumerate(self.model.layer):"
    $replacement = @"
        if hasattr(self.model, 'layer'):
            layer_stack = self.model.layer
        else:
            layer_stack = self.model.model.layer

        for i, layer_module in enumerate(layer_stack):
"@
    if ($content.Contains($needle)) {
        $patched = $content.Replace($needle, $replacement)
        Write-Host "  patching DINOv3 feature extractor (transformers>=4.50)..." -ForegroundColor DarkGray
        Set-Content -Path $file -Value $patched -NoNewline
    }
}

Write-Host ""
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host "  AL\CE - TRELLIS.2 Multi-view 3D Service" -ForegroundColor Magenta
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host ""

# -- Check repo exists --
if (-not (Test-Path $Trellis2MultiviewDir)) {
    Write-Host "  [X] TRELLIS.2.multiview not found at:" -ForegroundColor Red
    Write-Host "      $Trellis2MultiviewDir" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Clone it with:" -ForegroundColor Yellow
    Write-Host "    git clone https://huggingface.co/spaces/cpuai/Trellis.2.multiview `"$Trellis2MultiviewDir`"" -ForegroundColor Cyan
    exit 1
}

# -- Install mode --
if ($Install) {
    Write-Host "  -> Running TRELLIS.2 multi-view installation..." -ForegroundColor Yellow
    Write-Host "     (this may take 30-60 minutes; compiles CUDA extensions)" -ForegroundColor DarkGray
    Write-Host ""

    # Pre-flight: uv must be available (used to create the Python 3.10 venv).
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        Write-Host "  [X] 'uv' not found on PATH." -ForegroundColor Red
        Write-Host "      Install with: winget install --id=astral-sh.uv -e" -ForegroundColor Cyan
        exit 1
    }

    # Pre-flight: CUDA_HOME MUST point to CUDA 12.x (NOT 13.x).  See
    # start-trellis2.ps1 for the reasoning — the torch wheels we install
    # are compiled against cu128 and a mismatched nvcc trips the build.
    $cudaBase = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    $cuda12 = $null
    if (Test-Path $cudaBase) {
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

    $cudaBin = Join-Path $cuda12.FullName "bin"
    $cudaLibnvvp = Join-Path $cuda12.FullName "libnvvp"
    $cleanPath = ($env:PATH -split [IO.Path]::PathSeparator |
        Where-Object { $_ -and ($_ -notmatch [Regex]::Escape($cudaBase)) }) -join [IO.Path]::PathSeparator
    $env:PATH = $cudaBin + [IO.Path]::PathSeparator + $cudaLibnvvp + [IO.Path]::PathSeparator + $cleanPath

    $nvccCmd = Get-Command nvcc -ErrorAction SilentlyContinue
    if ($nvccCmd) { Write-Host "  nvcc on PATH:        $($nvccCmd.Source)" -ForegroundColor DarkGray }

    # MSVC (cl.exe): auto-import VS env via VsDevCmd.bat when missing.
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
                    $envDump = cmd /c "`"$vsDevCmd`" -arch=x64 -host_arch=x64 >NUL && set"
                    foreach ($line in $envDump) {
                        if ($line -match '^([^=]+)=(.*)$') {
                            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
                        }
                    }
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

    Push-Location $Trellis2MultiviewDir
    try {
        $VenvPython = Join-Path $Trellis2MultiviewDir ".venv\Scripts\python.exe"
        if (-not (Test-Path $VenvPython)) {
            Write-Host "  [1/8] Creating Python 3.10 venv..." -ForegroundColor Yellow
            & uv venv --python 3.10 .venv
            if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
        } else {
            Write-Host "  [1/8] Reusing existing venv at .venv" -ForegroundColor DarkGray
        }

        function Pip { param([Parameter(ValueFromRemainingArguments)]$args)
            & uv pip install --python $VenvPython @args
            if ($LASTEXITCODE -ne 0) { throw "uv pip install failed: $args" }
        }

        # 2. PyTorch + cu128 (matches Blackwell + the existing TRELLIS.2 stack).
        Write-Host "  [2/8] Installing PyTorch 2.7.0 (cu128)..." -ForegroundColor Yellow
        Pip torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128

        # 3. Basic Python deps.
        Write-Host "  [3/8] Installing basic dependencies..." -ForegroundColor Yellow
        Pip imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja `
            trimesh transformers gradio==6.0.1 tensorboard pandas lpips zstandard `
            kornia timm fastapi "uvicorn[standard]" python-multipart pillow gradio_client
        Pip "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

        # 4. flash-attn (prebuilt wheel where possible).  On Windows the
        # multi-view fork falls back to PyTorch's native sdpa backend if
        # flash-attn is unavailable, so installation failure here is not
        # fatal — but the prebuilt wheel speeds things up considerably.
        Write-Host "  [4/8] Installing flash-attn (cu128/torch2.7 prebuilt wheel)..." -ForegroundColor Yellow
        Pip --upgrade setuptools wheel packaging psutil ninja
        $flashWheel = "https://github.com/kingbri1/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu128torch2.7.0cxx11abiFALSE-cp310-cp310-win_amd64.whl"
        Write-Host "        downloading prebuilt wheel..." -ForegroundColor DarkGray
        & uv pip install --python $VenvPython $flashWheel
        if ($LASTEXITCODE -ne 0) {
            Write-Host "        prebuilt wheel unavailable - sdpa fallback will be used" -ForegroundColor Yellow
        }

        # 5. nvdiffrast.
        Write-Host "  [5/8] Installing nvdiffrast 0.4.0..." -ForegroundColor Yellow
        $extDir = Join-Path $env:TEMP "trellis2mv_ext"
        New-Item -ItemType Directory -Force -Path $extDir | Out-Null
        $nvd = Join-Path $extDir "nvdiffrast"
        if (-not (Test-Path $nvd)) {
            git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git $nvd
        }
        Pip $nvd --no-build-isolation

        # 6. nvdiffrec (renderutils).
        Write-Host "  [6/8] Installing nvdiffrec (renderutils)..." -ForegroundColor Yellow
        $nvdr = Join-Path $extDir "nvdiffrec"
        if (-not (Test-Path $nvdr)) {
            git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git $nvdr
        }
        Pip $nvdr --no-build-isolation

        # 7. CuMesh + FlexGEMM (CUDA C++ extensions).  See
        # start-trellis2.ps1 for the FlexGEMM Windows/MSVC patch
        # rationale (.template data_ptr<T>).
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

        # 8. o-voxel (vendored inside TRELLIS.2.multiview — installed in place).
        # Same Windows/MSVC patches required as for the single-image fork.
        Write-Host "  [8/8] Installing o-voxel..." -ForegroundColor Yellow
        $ovoxel = Join-Path $Trellis2MultiviewDir "o-voxel"
        if (-not (Test-Path $ovoxel)) {
            throw "o-voxel directory not found in $Trellis2MultiviewDir"
        }
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
        Patch-BiRefNetRmbg -Root $Trellis2MultiviewDir
        Patch-DinoV3FeatureExtractor -Root $Trellis2MultiviewDir
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "  [OK] TRELLIS.2 multi-view installation complete" -ForegroundColor Green
    Write-Host ""
}

# -- Check .venv exists --
$VenvPython = Join-Path $Trellis2MultiviewDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "  [X] TRELLIS.2.multiview .venv not found - run installation first:" -ForegroundColor Red
    Write-Host "      .\scripts\start-trellis2multiview.ps1 -Install" -ForegroundColor Cyan
    exit 1
}
Patch-BiRefNetRmbg -Root $Trellis2MultiviewDir
Patch-DinoV3FeatureExtractor -Root $Trellis2MultiviewDir

# -- Check server.py exists --
if (-not (Test-Path $ServerPy)) {
    Write-Host "  [X] server.py not found at: $ServerPy" -ForegroundColor Red
    exit 1
}

# -- Read model from config if not specified --
if (-not $Model) {
    $ConfigPath = Join-Path $AliceRoot "config\default.yaml"
    if (Test-Path $ConfigPath) {
        # The multi-view block uses ``trellis2multiview_model`` to keep the
        # YAML keys self-describing; fall back to the single-image block.
        $match = Select-String -Path $ConfigPath -Pattern '^\s*trellis2multiview_model:\s*"?([^"#]+)"?' | Select-Object -First 1
        if (-not $match) {
            $match = Select-String -Path $ConfigPath -Pattern '^\s*trellis2_model:\s*"?([^"#]+)"?' | Select-Object -First 1
        }
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
    $procId = $portInUse[0].OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "  [!] Port $Port already in use - TRELLIS.2 multi-view might be running" -ForegroundColor Yellow
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

# -- HuggingFace token (required: TRELLIS.2 pulls the gated facebook/dinov3-* repo) --
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
    $env:HUGGING_FACE_HUB_TOKEN = $env:HF_TOKEN
    Write-Host "  HF_TOKEN:   set (HuggingFace authentication enabled)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  [!] HF_TOKEN not set." -ForegroundColor Yellow
    Write-Host "      TRELLIS.2 needs the gated 'facebook/dinov3-vitl16-pretrain-lvd1689m' repo." -ForegroundColor Yellow
    Write-Host "      1) Request access:  https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m" -ForegroundColor Yellow
    Write-Host "      2) Create token:    https://huggingface.co/settings/tokens" -ForegroundColor Yellow
    Write-Host "      3) Add to alice\.env:  HF_TOKEN=hf_xxx" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "  -> Starting TRELLIS.2 multi-view microservice..." -ForegroundColor Yellow
Write-Host "     (first run downloads ~8GB of weights from HuggingFace)" -ForegroundColor DarkGray
Write-Host ""

& $VenvPython $ServerPy --model $Model --port $Port --output-dir $OutputDir --trellis2multiview-dir $Trellis2MultiviewDir
