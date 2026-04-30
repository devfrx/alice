# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the AL\\CE backend (onedir).

Run from the ``backend/`` directory::

    pyinstaller backend.spec --noconfirm --clean

Produces ``backend/dist/backend/`` containing ``backend.exe`` plus the
``_internal/`` runtime tree.  The ``scripts/build-installer.ps1`` helper
copies that directory into ``frontend/resources/backend/`` so
electron-builder can bundle it as ``extraResources``.

Notes
-----
* Entry point: ``backend/__main__.py`` — runs ``uvicorn.run`` against the
  string ``backend.core.app:create_app``.  PyInstaller therefore needs the
  full ``backend.*`` graph as hidden imports (uvicorn resolves the factory
  via ``importlib`` at runtime).
* The plugin manager auto-discovers plugins by scanning
  ``backend/plugins/`` on disk **and** by importing
  ``backend.plugins.<name>`` and ``backend.plugins.<name>.plugin``.  Each
  plugin package is enumerated explicitly below to guarantee the bytecode
  is shipped even if static analysis misses a transitive import.
* AI model files (LLM/STT/TTS) are NEVER bundled — see ``excludes``.  The
  first-run wizard (Phase 1.5) will download them on demand.
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# ``SPECPATH`` is injected by PyInstaller and points at the directory
# containing this spec file (``backend/``).  Resolve everything relative to
# the project root so the spec works whether invoked from ``backend/`` or
# from the repository root.
HERE = Path(SPECPATH).resolve()  # type: ignore[name-defined]
PROJECT_ROOT = HERE.parent
ENTRY = HERE / "__main__.py"

# ---------------------------------------------------------------------------
# Plugin packages — every directory under ``backend/plugins`` containing an
# ``__init__.py``.  Listed explicitly (instead of globbed) so the manifest
# is auditable and a missing entry produces an obvious diff.
# ---------------------------------------------------------------------------
# NOTE: ``home_automation`` ships only an empty ``__init__.py`` (placeholder
# for a future plugin) and would emit a ``backend.plugins.home_automation.plugin``
# "module not found" warning at PyInstaller analysis time — deliberately
# excluded.  Re-add when the package gains a real ``Plugin`` class.
PLUGIN_PACKAGES = [
    "cad_generator",
    "calendar",
    "chart_generator",
    "clipboard",
    "email_assistant",
    "file_search",
    "mcp_client",
    "media_control",
    "memory",
    "network_probe",
    "news",
    "notes",
    "notifications",
    "pc_automation",
    "system_info",
    "weather",
    "web_search",
    "whiteboard",
]

plugin_hidden: list[str] = []
plugin_datas: list[tuple[str, str]] = []
for name in PLUGIN_PACKAGES:
    plugin_hidden.append(f"backend.plugins.{name}")
    plugin_hidden.append(f"backend.plugins.{name}.plugin")
    # Pull every submodule so optional helpers (client.py, schema.py, ...)
    # are bundled even when imported lazily.
    plugin_hidden.extend(collect_submodules(f"backend.plugins.{name}"))
    # Pick up any non-Python data files declared next to the plugin
    # (templates, JSON schemas, .yaml fixtures).
    plugin_datas.extend(collect_data_files(f"backend.plugins.{name}"))

# ---------------------------------------------------------------------------
# Backend internals — submodules of ``backend.{core,api,db,services,tools}``
# ---------------------------------------------------------------------------
backend_hidden = (
    collect_submodules("backend.core")
    + collect_submodules("backend.api")
    + collect_submodules("backend.db")
    + collect_submodules("backend.services")
    + collect_submodules("backend.tools")
    + collect_submodules("backend.plugins")
)

# ---------------------------------------------------------------------------
# Third-party hidden imports — only packages that actually appear in
# ``pyproject.toml``.  Most are pulled in transitively, but listing them
# avoids the classic "module not found" failure when a dependency relies on
# dynamic ``importlib.import_module`` calls.
# ---------------------------------------------------------------------------
third_party_hidden = [
    "pydantic",
    "pydantic_settings",
    "httpx",
    "loguru",
    "sqlmodel",
    "sqlalchemy.dialects.sqlite",
    "aiosqlite",
    "qdrant_client",
    "uvicorn",
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "fastapi",
    "websockets",
    "watchfiles",
    "tiktoken",
    "tiktoken_ext.openai_public",
    "tiktoken_ext",
    "slowapi",
    # PyYAML provides the importable module ``yaml`` — the distribution
    # name ``pyyaml`` is *not* a valid hidden import target.
    "yaml",
    "jsonschema",
    # MCP client (optional but listed in deps)
    "mcp",
]

# Optional voice / embedding stacks — only added if installed in the
# current environment.  Missing ones are skipped silently to keep the spec
# usable in CPU-only or extras-less builds.
def _optional(name: str) -> list[str]:
    try:
        __import__(name)
    except Exception:  # noqa: BLE001 — any import failure means "skip"
        return []
    return [name]

optional_hidden: list[str] = []
optional_binaries: list[tuple[str, str]] = []
optional_datas: list[tuple[str, str]] = []

for opt in (
    "faster_whisper",
    "ctranslate2",
    "piper",
    "kokoro_onnx",
    "soundfile",
    "fastembed",
    "onnxruntime",
    "numpy",
    "pynvml",
):
    if not _optional(opt):
        continue
    optional_hidden.append(opt)
    optional_hidden.extend(collect_submodules(opt))
    # Native libraries (DLLs / .pyd / .so) — required for ctranslate2,
    # onnxruntime, soundfile, etc.
    optional_binaries.extend(collect_dynamic_libs(opt))
    optional_datas.extend(collect_data_files(opt))

# ---------------------------------------------------------------------------
# Bundled config files (NO models — see ``excludes``)
# ---------------------------------------------------------------------------
config_dir = PROJECT_ROOT / "config"
datas: list[tuple[str, str]] = []
if (config_dir / "default.yaml").exists():
    datas.append((str(config_dir / "default.yaml"), "config"))
if (config_dir / "system_prompt.md").exists():
    datas.append((str(config_dir / "system_prompt.md"), "config"))

datas.extend(plugin_datas)
datas.extend(optional_datas)

# ---------------------------------------------------------------------------
# Excludes — heavyweight packages we never want bundled.
# ``models/`` is a top-level directory, not a Python module, but listing
# the common offenders here keeps the bundle slim.
# ---------------------------------------------------------------------------
excludes = [
    "tkinter",
    "matplotlib",
    "IPython",
    "pytest",
    "pytest_asyncio",
    "pytest_cov",
    "ruff",
    "mypy",
    "TTS",  # XTTS extra — not part of default voice stack
]

hiddenimports = sorted(
    set(plugin_hidden + backend_hidden + third_party_hidden + optional_hidden)
)

# ---------------------------------------------------------------------------
# Analysis / Build
# ---------------------------------------------------------------------------
block_cipher = None

a = Analysis(  # noqa: F821 — injected by PyInstaller
    [str(ENTRY)],
    pathex=[str(PROJECT_ROOT), str(HERE)],
    binaries=optional_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="backend",
)
