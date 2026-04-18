# TRELLIS.2 — Setup & Avvio (Windows)

> Guida per integrare **TRELLIS.2** (`microsoft/TRELLIS.2-4B`) come microservizio
> 3D parallelo a TRELLIS classico in AL\CE.

## 1. Architettura

```
┌────────────────────────────────┐      ┌──────────────────────────────┐
│  AL\CE Backend (Python 3.14)   │      │  TRELLIS classico  :8090     │
│                                │──────┤  (TRELLIS-for-windows)       │
│  - cad_generator plugin        │      └──────────────────────────────┘
│  - VRAM swap (unload LLM)      │      ┌──────────────────────────────┐
│  - httpx async client          │──────┤  TRELLIS.2  :8091            │
│                                │      │  (microsoft/TRELLIS.2-4B)    │
└────────────────────────────────┘      └──────────────────────────────┘
```

I due servizi sono **completamente indipendenti**: venv, porte, output dir,
config separate. Possono coesistere o essere avviati uno alla volta.

## 2. Differenze chiave vs TRELLIS classico

| Caratteristica | TRELLIS classico | TRELLIS.2 |
| --- | --- | --- |
| **Modelli** | text + image | **solo image** |
| **Parametri** | 342M / 1.1B / 1.2B | 4B |
| **VRAM minima** | ~12 GB | ~24 GB consigliata |
| **Output** | mesh + gaussian (`postprocessing_utils`) | O-Voxel (`o_voxel.postprocess`) |
| **Porta default** | 8090 | 8091 |
| **Risoluzione** | fissa | `512` / `1024` / `1024_cascade` / `1536_cascade` |
| **OS supportato** | Windows (fork `devfrx`) | Linux (Windows: best-effort) |

## 3. Clone (gia' eseguito)

```powershell
cd C:\Users\Jays\Desktop\alice
git clone --recurse-submodules https://github.com/microsoft/TRELLIS.2.git
```

Layout risultante:

```
C:\Users\Jays\Desktop\alice\
├── alice\
│   ├── trellis_server\server.py         ← microservizio TRELLIS classico
│   ├── trellis2_server\server.py        ← microservizio TRELLIS.2
│   └── scripts\
│       ├── start-trellis.ps1
│       └── start-trellis2.ps1
├── TRELLIS-for-windows\                  ← fork Windows di TRELLIS classico
└── TRELLIS.2\                            ← repo upstream Microsoft
    ├── trellis2\
    ├── o-voxel\        (vendored)
    └── .venv\          (creato dall'installer)
```

## 4. Installazione

```powershell
.\scripts\start-trellis2.ps1 -Install
```

Lo script porta su Windows i passi di [`setup.sh`](https://github.com/microsoft/TRELLIS.2/blob/main/setup.sh):

| Step | Pacchetto | Note |
| --- | --- | --- |
| 1 | venv Python 3.10 (uv) | `TRELLIS.2\.venv` |
| 2 | torch 2.6.0 + torchvision 0.21.0 (cu124) | da `download.pytorch.org/whl/cu124` |
| 3 | basic deps (imageio, opencv, transformers, gradio, ecc.) | + `utils3d` da git |
| 4 | flash-attn 2.7.3 | wheel precompilato se disponibile |
| 5 | nvdiffrast 0.4.0 | clone NVlabs, compilato con `--no-build-isolation` |
| 6 | nvdiffrec (`renderutils`) | fork JeffreyXiang |
| 7 | CuMesh + FlexGEMM | estensioni CUDA C++ (compilano con `nvcc`) |
| 8 | o-voxel | vendored in `TRELLIS.2\o-voxel` |

### Prerequisiti

| Componente | Versione | Note |
| --- | --- | --- |
| `uv` | latest | `winget install --id=astral-sh.uv -e` |
| CUDA Toolkit | 12.4 (consigliato) | Lo script auto-rileva l'installazione piu' recente in `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\` |
| Visual Studio Build Tools | 2022 (o 2025 con [patch host_config.h](trellis-setup.md#6-patch-host_configh-per-vs-2025-msvc-1950)) | per compilare `nvcc` |
| GPU NVIDIA | ≥ 24 GB VRAM (raccomandato) | RTX 3090/4090/5090 ok; sm_120 (Blackwell) richiede `TORCH_CUDA_ARCH_LIST` con `12.0` |

> **Nota Blackwell (RTX 5080/5090):** lo script imposta automaticamente
> `TORCH_CUDA_ARCH_LIST=8.0;8.6;8.9;9.0;12.0`. Se torch 2.6+cu124 non
> supporta sm_120 sul tuo hardware potresti dover passare a torch 2.7+cu128
> manualmente (vedi [trellis-setup.md §4](trellis-setup.md#4-aggiornamenti-pytorch-per-blackwell-cu128)).

## 5. Avvio

```powershell
# avvio standard (porta 8091, modello da config)
.\scripts\start-trellis2.ps1

# porta custom
.\scripts\start-trellis2.ps1 -Port 9000

# modello custom (oggi solo TRELLIS.2-4B)
.\scripts\start-trellis2.ps1 -Model microsoft/TRELLIS.2-4B
```

Al primo avvio scarica ~8 GB di pesi da HuggingFace.

## 6. Endpoints

Identici per filosofia a quelli di TRELLIS classico (porta 8090):

| Metodo | Path | Body | Risposta |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{status, gpu_available, vram_free_mb, model_loaded}` |
| `POST` | `/generate` | multipart: `image`, `seed`, `output_name`, `pipeline_type`, `decimation_target`, `texture_size` | `{model_name, file_path, format:"glb", size_bytes}` |
| `POST` | `/unload` | — | `{status:"unloaded"}` |
| `POST` | `/load` | form: `model` | `{status, model_name}` |
| `GET` | `/models/{name}` | — | file GLB |

Esempio:

```powershell
curl -X POST http://localhost:8091/generate `
  -F "image=@T.png" `
  -F "pipeline_type=1024" `
  -F "seed=42"
```

## 7. Configurazione AL\CE

`config/default.yaml` espone il blocco `trellis2:` (parallelo a `trellis:`):

```yaml
trellis2:
  enabled: false                # accendere quando si vuole usare TRELLIS.2
  service_url: "http://localhost:8091"
  trellis2_model: "microsoft/TRELLIS.2-4B"
  pipeline_type: "512"          # 512 | 1024 | 1024_cascade | 1536_cascade
  decimation_target: 1000000
  texture_size: 4096
  auto_vram_swap: true
  request_timeout_s: 600
  seed: -1
```

Override via env vars con prefisso `ALICE_TRELLIS2__`, es:
`$env:ALICE_TRELLIS2__PIPELINE_TYPE = "1024"`.
