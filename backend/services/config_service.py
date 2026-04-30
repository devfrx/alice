"""AL\\CE — Layered configuration service.

Implements a four-layer configuration model on top of the existing
:class:`backend.core.config.AliceConfig` (pydantic-settings v2):

    1. ``defaults``  — bundled ``config/default.yaml``.
    2. ``system``    — ``%LOCALAPPDATA%\\Alice\\config\\system.yaml``
                       (admin/install-time, optional).
    3. ``user``      — ``%LOCALAPPDATA%\\Alice\\config\\user.yaml``
                       (UI Settings page writes here).
    4. ``runtime``   — in-memory ephemeral overrides.

Layers are deep-merged in the order above (later layers override earlier
ones) into a single dict, which is then passed to
:class:`AliceConfig` as ``__init__`` kwargs for validation.

Env-var precedence
~~~~~~~~~~~~~~~~~~
``AliceConfig.settings_customise_sources`` already returns
``(env_settings, init_settings, ...)`` — meaning ``ALICE_*`` env vars take
precedence over init kwargs.  Because we pass the merged YAML dict as
init kwargs, env vars naturally win over every YAML layer **without any
extra wiring on our side**.  This is the chosen mechanism: a single call
to ``AliceConfig(**merged_dict)`` lets pydantic-settings layer env vars on
top of the merged YAML.
"""

from __future__ import annotations

import asyncio
import copy
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from backend.core.config import (
    DEFAULT_CONFIG_PATH,
    AliceConfig,
    _load_yaml,
)
from backend.core.event_bus import EventBus

# ---------------------------------------------------------------------------
# Layer enum
# ---------------------------------------------------------------------------


class ConfigLayer(StrEnum):
    """Configuration layers, ordered from lowest to highest precedence."""

    DEFAULTS = "defaults"
    SYSTEM = "system"
    USER = "user"
    RUNTIME = "runtime"


_LAYER_ORDER: tuple[ConfigLayer, ...] = (
    ConfigLayer.DEFAULTS,
    ConfigLayer.SYSTEM,
    ConfigLayer.USER,
    ConfigLayer.RUNTIME,
)


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def get_config_dir() -> Path:
    """Return the directory hosting ``system.yaml`` / ``user.yaml``.

    Resolution order:

    * Windows: ``%LOCALAPPDATA%\\Alice\\config``
    * Linux / macOS: ``$XDG_CONFIG_HOME/alice`` if set, else
      ``~/.config/alice``.

    The directory is created on first access.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            root = Path(base) / "Alice" / "config"
        else:  # extremely unusual on Windows, fall back to home
            root = Path.home() / "AppData" / "Local" / "Alice" / "config"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg) / "alice" if xdg else Path.home() / ".config" / "alice"

    root.mkdir(parents=True, exist_ok=True)
    return root


def get_system_config_path() -> Path:
    """Return path to ``system.yaml`` (may not exist)."""
    return get_config_dir() / "system.yaml"


def get_user_config_path() -> Path:
    """Return path to ``user.yaml`` (may not exist)."""
    return get_config_dir() / "user.yaml"


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into ``base`` (in-place).

    Dicts are merged recursively; scalars and lists in ``overlay`` replace
    the corresponding value in ``base``.  Returns ``base``.
    """
    for key, value in overlay.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _set_dotted(target: dict[str, Any], path: str, value: Any) -> None:
    """Set ``value`` at dotted ``path`` in ``target`` (creating dicts as needed).

    Raises ``ValueError`` when an intermediate node exists but is not a dict.
    """
    if not path:
        raise ValueError("path must be a non-empty dotted string")
    parts = path.split(".")
    node: Any = target
    for part in parts[:-1]:
        existing = node.get(part)
        if existing is None:
            node[part] = {}
            node = node[part]
        elif isinstance(existing, dict):
            node = existing
        else:
            raise ValueError(
                f"cannot descend into non-dict node '{part}' on path '{path}'"
            )
    node[parts[-1]] = value


def _get_dotted(source: Any, path: str) -> Any:
    """Lookup dotted ``path`` against ``source`` (Pydantic model or dict).

    Raises ``KeyError`` when any segment is missing.
    """
    if not path:
        raise KeyError("path must be a non-empty dotted string")
    node: Any = source
    for part in path.split("."):
        if isinstance(node, dict):
            if part not in node:
                raise KeyError(path)
            node = node[part]
        else:
            if not hasattr(node, part):
                raise KeyError(path)
            node = getattr(node, part)
    return node


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _read_yaml_safe(path: Path) -> dict[str, Any]:
    """Read a YAML file, returning ``{}`` if missing or empty."""
    if not path.exists():
        return {}
    try:
        return _load_yaml(path)
    except Exception as exc:  # noqa: BLE001 — config corruption must not crash startup
        logger.warning("Failed to parse config file {}: {}", path, exc)
        return {}


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    """Atomically write ``data`` to ``path`` as YAML (sync helper)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# LayeredConfigService
# ---------------------------------------------------------------------------


class LayeredConfigService:
    """Hold and reconcile the four configuration layers.

    The merged dict is rebuilt and validated through :class:`AliceConfig`
    on every mutation.  Validation errors raised by Pydantic propagate to
    the caller; the layer dict on disk is **only** updated after successful
    validation.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        defaults_path: Path | None = None,
        system_path: Path | None = None,
        user_path: Path | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._defaults_path = defaults_path or DEFAULT_CONFIG_PATH
        self._system_path = system_path or get_system_config_path()
        self._user_path = user_path or get_user_config_path()

        self._layers: dict[ConfigLayer, dict[str, Any]] = {
            ConfigLayer.DEFAULTS: {},
            ConfigLayer.SYSTEM: {},
            ConfigLayer.USER: {},
            ConfigLayer.RUNTIME: {},
        }
        self._resolved: AliceConfig | None = None
        self._lock = asyncio.Lock()

        self._load_disk_layers()
        self._rebuild()

    # -- disk loading ----------------------------------------------------

    def _load_disk_layers(self) -> None:
        """Read defaults/system/user YAML files into the layer dicts."""
        self._layers[ConfigLayer.DEFAULTS] = _read_yaml_safe(self._defaults_path)
        self._layers[ConfigLayer.SYSTEM] = _read_yaml_safe(self._system_path)
        self._layers[ConfigLayer.USER] = _read_yaml_safe(self._user_path)
        logger.debug(
            "Loaded config layers: defaults={}, system={} (exists={}), user={} (exists={})",
            self._defaults_path,
            self._system_path,
            self._system_path.exists(),
            self._user_path,
            self._user_path.exists(),
        )

    def reload(self) -> AliceConfig:
        """Re-read disk layers (defaults/system/user) and revalidate.

        ``runtime`` overrides are preserved.  Returns the new resolved
        :class:`AliceConfig`.
        """
        self._load_disk_layers()
        self._rebuild()
        assert self._resolved is not None
        return self._resolved

    # -- merge / validation ----------------------------------------------

    def _merged_dict(self) -> dict[str, Any]:
        """Return a fresh deep-merge of all layers in precedence order."""
        merged: dict[str, Any] = {}
        for layer in _LAYER_ORDER:
            _deep_merge(merged, self._layers[layer])
        return merged

    def _rebuild(self) -> None:
        """Validate the merged dict into a new :class:`AliceConfig`.

        Env vars (``ALICE_*``) override the merged dict because
        :meth:`AliceConfig.settings_customise_sources` returns
        ``env_settings`` before ``init_settings``.
        """
        merged = self._merged_dict()
        self._resolved = AliceConfig(**merged)

    # -- public read API -------------------------------------------------

    def get_resolved(self) -> AliceConfig:
        """Return the currently validated :class:`AliceConfig`."""
        if self._resolved is None:  # pragma: no cover — defensive
            self._rebuild()
        assert self._resolved is not None
        return self._resolved

    def get(self, path: str) -> Any:
        """Lookup a dotted ``path`` against the resolved config.

        Example: ``svc.get("server.port")`` -> ``8000``.

        Raises:
            KeyError: when any segment of the path is missing.
        """
        return _get_dotted(self.get_resolved(), path)

    def get_layer(self, layer: ConfigLayer) -> dict[str, Any]:
        """Return a deep-copy of the raw dict stored in ``layer``."""
        return copy.deepcopy(self._layers[layer])

    def get_all_layers(self) -> dict[str, dict[str, Any]]:
        """Return a deep-copy of every layer dict, keyed by layer name."""
        return {layer.value: copy.deepcopy(self._layers[layer]) for layer in _LAYER_ORDER}

    # -- public write API ------------------------------------------------

    async def set(
        self,
        path: str,
        value: Any,
        layer: ConfigLayer = ConfigLayer.USER,
    ) -> AliceConfig:
        """Set a dotted ``path`` in ``layer``, validate, persist, and notify.

        Workflow:

        1. Mutate a tentative copy of the target layer.
        2. Re-validate the merged dict through :class:`AliceConfig`.
        3. On success, commit the new layer dict in memory; persist
           ``system``/``user`` layers to disk atomically.
        4. Emit ``config.changed`` on the event bus.

        Args:
            path: Dotted path (e.g. ``"llm.temperature"``).
            value: New value (any JSON-serialisable Python object).
            layer: Target layer.  Defaults to :attr:`ConfigLayer.USER`.

        Returns:
            The new resolved :class:`AliceConfig`.

        Raises:
            ValueError: when ``path`` is invalid or descends into a non-dict.
            pydantic.ValidationError: when the resulting config fails
                validation.  Disk and in-memory state remain unchanged.
        """
        async with self._lock:
            tentative = copy.deepcopy(self._layers[layer])
            _set_dotted(tentative, path, value)

            # Build a tentative merged dict and validate.
            merged: dict[str, Any] = {}
            for lyr in _LAYER_ORDER:
                src = tentative if lyr is layer else self._layers[lyr]
                _deep_merge(merged, src)
            new_resolved = AliceConfig(**merged)

            # Validation succeeded — commit in-memory.
            self._layers[layer] = tentative
            self._resolved = new_resolved

            # Persist disk-backed layers.
            if layer in (ConfigLayer.SYSTEM, ConfigLayer.USER):
                target_path = (
                    self._system_path
                    if layer is ConfigLayer.SYSTEM
                    else self._user_path
                )
                await asyncio.to_thread(_write_yaml_atomic, target_path, tentative)
                logger.info(
                    "Persisted config change ({} = {!r}) to {}",
                    path, value, target_path,
                )
            else:
                logger.debug("Runtime config change ({} = {!r})", path, value)

        # Emit outside the lock so handlers can call back into the service.
        if self._event_bus is not None:
            try:
                await self._event_bus.emit(
                    "config.changed",
                    path=path,
                    value=value,
                    layer=layer.value,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("config.changed handler raised: {}", exc)

        return new_resolved

    async def reset_runtime(self) -> AliceConfig:
        """Drop every runtime override and revalidate."""
        async with self._lock:
            self._layers[ConfigLayer.RUNTIME] = {}
            self._rebuild()
            assert self._resolved is not None
            return self._resolved
