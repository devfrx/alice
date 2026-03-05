"""O.M.N.I.A. — Plugin manager (discovery, lifecycle, dependency resolution).

Manages the full plugin lifecycle: registration, dependency resolution via
topological sort, initialisation, hot-reload, and graceful shutdown.  The
static ``PLUGIN_REGISTRY`` is populated at import time by each plugin module
for PyInstaller compatibility.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import sys
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlmodel import SQLModel

if TYPE_CHECKING:
    from backend.core.context import AppContext

from backend.core.event_bus import OmniaEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import ConnectionStatus

# -------------------------------------------------------------------
# Static plugin registry — populated by each plugin at import time
# -------------------------------------------------------------------

PLUGIN_REGISTRY: dict[str, type[BasePlugin]] = {}
"""Module-level registry.  Each plugin calls
``PLUGIN_REGISTRY["name"] = MyPlugin`` on import for PyInstaller compat.
"""

# -------------------------------------------------------------------
# Plugin manager
# -------------------------------------------------------------------


class PluginManager:
    """Orchestrates plugin discovery, ordering, and lifecycle.

    Uses Kahn's algorithm for topological dependency resolution and
    provides async startup / shutdown with crash-isolation per plugin.
    """

    def __init__(self, ctx: AppContext) -> None:
        """Initialise the manager with an application context.

        Args:
            ctx: The shared ``AppContext`` instance.
        """
        self._ctx = ctx
        self._plugins: dict[str, BasePlugin] = {}
        self._load_order: list[str] = []
        self._failed_plugins: set[str] = set()
        self._lock = asyncio.Lock()
        self._logger = logger.bind(component="PluginManager")

    # ---------------------------------------------------------------
    # Public lifecycle
    # ---------------------------------------------------------------

    async def startup(self) -> None:
        """Execute the full plugin startup sequence.

        Steps:
            1. Read enabled list from config.
            2. Optionally discover plugins dynamically.
            3. Filter against ``PLUGIN_REGISTRY``.
            4. Resolve load order (topological sort).
            5. Instantiate → initialise each plugin.
            6. Create DB tables for plugin models.
            7. Call ``on_app_startup`` on every loaded plugin.
        """
        enabled = list(self._ctx.config.plugins.enabled)

        # Dynamic discovery (dev-only)
        if (
            os.environ.get("OMNIA_PLUGIN_DISCOVERY") == "dynamic"
        ):
            self._discover_plugins()

        # Filter unknown plugins
        valid: list[str] = []
        for name in enabled:
            if name in PLUGIN_REGISTRY:
                valid.append(name)
            else:
                self._logger.warning(
                    "Plugin '{}' listed in config but not found "
                    "in PLUGIN_REGISTRY — skipping",
                    name,
                )

        # Resolve dependency order
        self._load_order = self._resolve_load_order(valid)

        # Instantiate & initialise
        loaded = 0
        for name in self._load_order:
            plugin_cls = PLUGIN_REGISTRY[name]
            plugin = plugin_cls()
            try:
                await plugin.initialize(self._ctx)
                self._plugins[name] = plugin
                loaded += 1
                await self._ctx.event_bus.emit(
                    OmniaEvent.PLUGIN_LOADED,
                    plugin_name=name,
                    version=plugin.plugin_version,
                )
                self._logger.info(
                    "Plugin '{}' v{} initialised",
                    name,
                    plugin.plugin_version,
                )
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' failed to initialise: {}",
                    name,
                    exc,
                )
                self._failed_plugins.add(name)
                await self._ctx.event_bus.emit(
                    OmniaEvent.PLUGIN_FAILED,
                    plugin_name=name,
                    error=str(exc),
                )

        # DB table creation
        await self._create_plugin_tables()

        # on_app_startup hooks
        for name in self._load_order:
            plugin = self._plugins.get(name)
            if plugin is None:
                continue
            try:
                await plugin.on_app_startup()
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' on_app_startup error: {}",
                    name,
                    exc,
                )

        self._logger.info(
            "Plugin startup complete: {}/{} loaded",
            loaded,
            len(self._load_order),
        )

    async def shutdown(self) -> None:
        """Shut down all plugins in reverse load order.

        Calls ``on_app_shutdown`` then ``cleanup`` on each plugin.
        Exceptions are caught so one failing plugin cannot block
        the rest.
        """
        for name in reversed(self._load_order):
            plugin = self._plugins.get(name)
            if plugin is None:
                continue
            try:
                await plugin.on_app_shutdown()
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' on_app_shutdown error: {}",
                    name,
                    exc,
                )
            try:
                await plugin.cleanup()
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' cleanup error: {}",
                    name,
                    exc,
                )

        self._plugins.clear()
        self._logger.info("All plugins shut down")

    async def reload_plugin(self, name: str) -> bool:
        """Hot-reload a single plugin by name.

        Cleans up the existing instance, reimports the module,
        re-instantiates, and re-initialises.

        Args:
            name: The plugin name to reload.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        async with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                self._logger.warning(
                    "Cannot reload '{}': not loaded", name,
                )
                return False

            # Cleanup existing instance
            try:
                await plugin.cleanup()
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' cleanup during reload: {}",
                    name,
                    exc,
                )

            # Re-import the module
            module_path = f"backend.plugins.{name}.plugin"
            try:
                module = sys.modules.get(module_path)
                if module is not None:
                    importlib.reload(module)
                else:
                    importlib.import_module(module_path)

                # Re-read the class from the registry
                plugin_cls = PLUGIN_REGISTRY.get(name)
                if plugin_cls is None:
                    self._logger.error(
                        "Plugin '{}' not in registry after reload",
                        name,
                    )
                    del self._plugins[name]
                    return False

                new_plugin = plugin_cls()
                await new_plugin.initialize(self._ctx)
                self._plugins[name] = new_plugin
                self._logger.info("Plugin '{}' reloaded", name)
                return True
            except Exception as exc:
                self._logger.error(
                    "Failed to reload plugin '{}': {}",
                    name,
                    exc,
                )
                self._plugins.pop(name, None)
                return False

    # ---------------------------------------------------------------
    # Accessors
    # ---------------------------------------------------------------

    def get_plugin(self, name: str) -> BasePlugin | None:
        """Return a loaded plugin by name, or ``None``.

        Args:
            name: The plugin name.

        Returns:
            The ``BasePlugin`` instance or ``None``.
        """
        return self._plugins.get(name)

    def get_all_plugins(self) -> dict[str, BasePlugin]:
        """Return a shallow copy of all loaded plugins.

        Returns:
            Dict mapping plugin name → instance.
        """
        return dict(self._plugins)

    def get_loaded_plugin_names(self) -> list[str]:
        """Return names of all successfully loaded plugins.

        Returns:
            List of plugin name strings.
        """
        return list(self._plugins.keys())

    async def get_all_status(
        self,
    ) -> dict[str, ConnectionStatus]:
        """Query each plugin for its connection status.

        Returns:
            Dict mapping plugin name → ``ConnectionStatus``.
        """
        statuses: dict[str, ConnectionStatus] = {}
        for name, plugin in self._plugins.items():
            try:
                statuses[name] = (
                    await plugin.get_connection_status()
                )
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' status check failed: {}",
                    name,
                    exc,
                )
                statuses[name] = ConnectionStatus.ERROR
        return statuses

    async def health_check(self) -> bool:
        """Return ``True`` if at least one plugin is loaded and none in ERROR.

        Returns:
            Health status boolean.
        """
        if not self._plugins:
            return False
        statuses = await self.get_all_status()
        return not any(
            s == ConnectionStatus.ERROR for s in statuses.values()
        )

    # ---------------------------------------------------------------
    # Dependency resolution (Kahn's algorithm)
    # ---------------------------------------------------------------

    def _resolve_load_order(
        self, plugin_names: list[str],
    ) -> list[str]:
        """Topologically sort plugins by their dependencies.

        Uses Kahn's algorithm with a secondary descending sort by
        ``plugin_priority`` within each zero-in-degree batch.

        Args:
            plugin_names: Plugins to order.

        Returns:
            Ordered list of plugin names.

        Raises:
            ValueError: If a dependency cycle is detected.
        """
        name_set = set(plugin_names)

        # Build adjacency and in-degree maps
        in_degree: dict[str, int] = {n: 0 for n in plugin_names}
        dependents: dict[str, list[str]] = {
            n: [] for n in plugin_names
        }

        for name in plugin_names:
            cls = PLUGIN_REGISTRY[name]
            for dep in cls.plugin_dependencies:
                if dep not in name_set:
                    if dep not in PLUGIN_REGISTRY:
                        self._logger.warning(
                            "Plugin '{}' depends on '{}' which "
                            "is not available",
                            name,
                            dep,
                        )
                    continue
                in_degree[name] += 1
                dependents[dep].append(name)

        # Seed the queue with zero-in-degree nodes sorted by
        # priority (descending)
        queue: deque[str] = deque(
            sorted(
                (n for n in plugin_names if in_degree[n] == 0),
                key=lambda n: PLUGIN_REGISTRY[n].plugin_priority,
                reverse=True,
            )
        )

        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            # Collect next candidates and sort by priority
            candidates: list[str] = []
            for dep in dependents[node]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    candidates.append(dep)
            candidates.sort(
                key=lambda n: PLUGIN_REGISTRY[n].plugin_priority,
                reverse=True,
            )
            queue.extend(candidates)

        if len(order) != len(plugin_names):
            remaining = name_set - set(order)
            raise ValueError(
                "Dependency cycle detected among plugins: "
                f"{', '.join(sorted(remaining))}"
            )

        return order

    # ---------------------------------------------------------------
    # Dynamic discovery (dev only)
    # ---------------------------------------------------------------

    def _discover_plugins(self) -> None:
        """Scan ``backend/plugins/`` for plugin modules.

        Only executed when the environment variable
        ``OMNIA_PLUGIN_DISCOVERY=dynamic`` is set.  Each plugin
        subdirectory must contain a ``plugin.py`` exporting a class
        that extends ``BasePlugin``.
        """
        plugins_dir = (
            Path(__file__).resolve().parents[1] / "plugins"
        )
        if not plugins_dir.is_dir():
            self._logger.warning(
                "Plugins directory not found: {}", plugins_dir,
            )
            return

        for child in sorted(plugins_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            plugin_file = child / "plugin.py"
            if not plugin_file.exists():
                continue
            if child.name in PLUGIN_REGISTRY:
                continue

            module_path = (
                f"backend.plugins.{child.name}.plugin"
            )
            try:
                mod = importlib.import_module(module_path)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, BasePlugin)
                        and attr is not BasePlugin
                    ):
                        PLUGIN_REGISTRY[child.name] = attr
                        self._logger.info(
                            "Discovered plugin '{}' → {}",
                            child.name,
                            attr.__qualname__,
                        )
                        break
            except Exception as exc:
                self._logger.error(
                    "Failed to discover plugin '{}': {}",
                    child.name,
                    exc,
                )

    # ---------------------------------------------------------------
    # DB table creation
    # ---------------------------------------------------------------

    async def _create_plugin_tables(self) -> None:
        """Ensure database tables exist for all registered SQLModel models.

        Calls ``SQLModel.metadata.create_all`` which is idempotent — tables
        already created by ``init_db`` at startup are skipped.  This catches
        any additional models registered by plugins via ``get_db_models()``.
        """
        if self._ctx.db is None:
            self._logger.debug(
                "No database session — skipping table creation",
            )
            return

        models: list[type] = []
        for name, plugin in self._plugins.items():
            try:
                models.extend(plugin.get_db_models())
            except Exception as exc:
                self._logger.error(
                    "Plugin '{}' get_db_models error: {}",
                    name,
                    exc,
                )

        if not models:
            return

        if self._ctx.engine is None:
            self._logger.warning(
                "No engine available — skipping table creation",
            )
            return

        try:
            async with self._ctx.engine.begin() as conn:
                await conn.run_sync(
                    SQLModel.metadata.create_all,
                )
            self._logger.debug(
                "Created tables for {} plugin model(s)",
                len(models),
            )
        except Exception as exc:
            self._logger.error(
                "Failed to create plugin tables: {}", exc,
            )
