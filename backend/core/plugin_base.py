"""O.M.N.I.A. — Base plugin class.

Every OMNIA plugin **must** subclass :class:`BasePlugin` and implement
the two abstract methods :meth:`get_tools` and :meth:`execute_tool`.
The lifecycle methods (:meth:`initialize`, :meth:`cleanup`,
:meth:`on_app_startup`, :meth:`on_app_shutdown`) provide hooks that
the plugin manager calls at well-defined moments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from loguru import logger as _loguru_logger

from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
    PLUGIN_API_VERSION,
)

if TYPE_CHECKING:
    from loguru import Logger
    from backend.core.context import AppContext


class BasePlugin(ABC):
    """Abstract base class for all OMNIA plugins.

    Subclasses **must** define the four class-level attributes
    (``plugin_name``, ``plugin_version``, ``plugin_description``,
    ``plugin_dependencies``) and implement :meth:`get_tools` /
    :meth:`execute_tool`.

    Attributes:
        plugin_name: Unique identifier matching the plugin registry key.
        plugin_version: Semantic version string (e.g. ``"1.0.0"``).
        plugin_description: Human-readable one-liner.
        plugin_dependencies: Names of plugins that must load first.
        plugin_priority: Execution order 0–100 (higher = more priority).
        requires_user_confirmation: Whether destructive operations need
            explicit user approval before execution.
    """

    # ------------------------------------------------------------------
    # Class-level attributes — override in every subclass
    # ------------------------------------------------------------------
    plugin_name: str
    plugin_version: str
    plugin_description: str
    plugin_author: str = ""
    plugin_dependencies: list[str] = []
    plugin_priority: int = 50
    requires_user_confirmation: bool = False

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        """Initialise internal state.

        No side-effects, no I/O — only attribute setup.
        """
        self._ctx: AppContext | None = None
        self._initialized: bool = False
        self._logger = _loguru_logger.bind(plugin=self.plugin_name)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def logger(self) -> Logger:
        """Pre-configured *loguru* logger bound to this plugin."""
        return self._logger

    @property
    def ctx(self) -> AppContext:
        """Return the application context.

        Raises:
            RuntimeError: If the plugin has not been initialised yet.
        """
        if self._ctx is None:
            raise RuntimeError(
                f"Plugin '{self.plugin_name}' has not been "
                "initialised — call initialize() first."
            )
        return self._ctx

    @property
    def is_initialized(self) -> bool:
        """Whether :meth:`initialize` has completed successfully."""
        return self._initialized

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Store the application context and mark the plugin as ready.

        Subclasses should call ``await super().initialize(ctx)`` first
        and then perform any I/O-bound setup (opening files, connecting
        to external services, etc.).

        Args:
            ctx: The shared application context (DI container).
        """
        self._ctx = ctx
        self._initialized = True
        self._logger.info(
            "Plugin initialised (v{version}, API {api})",
            version=self.plugin_version,
            api=PLUGIN_API_VERSION,
        )

    async def cleanup(self) -> None:
        """Release resources acquired during :meth:`initialize`.

        Subclasses should release their own resources **first** and
        then call ``await super().cleanup()``.
        """
        self._initialized = False
        self._logger.debug("Plugin cleaned up")

    async def on_app_startup(self) -> None:
        """Called after **all** plugins have been initialised.

        Use this for work that depends on other plugins being ready
        (e.g. subscribing to MQTT topics via a broker plugin).
        """

    async def on_app_shutdown(self) -> None:
        """Called just before :meth:`cleanup`.

        Use for graceful disconnection from external services.
        """

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @abstractmethod
    def get_tools(self) -> list[ToolDefinition]:
        """Return the tool definitions this plugin exposes.

        May return an empty list — not every plugin provides tools.
        """

    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute *tool_name* with the supplied arguments.

        Args:
            tool_name: Identifier matching a ``ToolDefinition.name``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata (session, conversation, …).

        Returns:
            A :class:`ToolResult` describing success or failure.
        """

    async def cancel_tool(
        self,
        tool_name: str,
        execution_id: str,
    ) -> None:
        """Cancel a running tool execution.

        Override for tools that declare ``supports_cancellation=True``.

        Args:
            tool_name: The tool to cancel.
            execution_id: Unique id of the running execution.
        """

    # ------------------------------------------------------------------
    # Hook methods
    # ------------------------------------------------------------------

    async def pre_execution_hook(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> bool:
        """Gate that runs before every tool execution.

        Return ``True`` to proceed or ``False`` to abort. Override
        in plugins that require user confirmation for destructive
        operations.

        Args:
            tool_name: Tool about to be executed.
            args: Arguments that will be forwarded.

        Returns:
            Whether execution should continue.
        """
        return True

    # ------------------------------------------------------------------
    # Dependency / health methods
    # ------------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Return names of missing **optional** dependencies.

        The default implementation reports nothing missing. Override
        to inspect the environment for required binaries, packages,
        or services.

        Returns:
            A list of human-readable dependency descriptions.
        """
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Report the current connection / health status.

        Returns:
            A :class:`ConnectionStatus` enum member.
        """
        return ConnectionStatus.UNKNOWN

    async def on_dependency_status_change(
        self,
        plugin_name: str,
        status: ConnectionStatus,
    ) -> None:
        """Notified when a dependency plugin's status changes.

        Args:
            plugin_name: The plugin whose status changed.
            status: The new status.
        """

    # ------------------------------------------------------------------
    # Configuration class-methods
    # ------------------------------------------------------------------

    @classmethod
    def get_config_schema(cls) -> dict:
        """Return a JSON Schema describing plugin-specific config.

        Returns:
            A JSON Schema ``object``.  Default: empty object.
        """
        return {"type": "object", "properties": {}}

    @classmethod
    def get_db_models(cls) -> list[type]:
        """Return SQLModel classes for plugin-owned DB tables.

        The plugin manager will ensure these tables exist before
        :meth:`initialize` is called.

        Returns:
            A list of SQLModel model classes.
        """
        return []

    @classmethod
    async def migrate_config(
        cls,
        from_version: str,
        old_config: dict,
        to_version: str,
    ) -> dict:
        """Migrate plugin config between versions.

        Args:
            from_version: The version the config was written for.
            old_config: The existing configuration dict.
            to_version: The target version to migrate to.

        Returns:
            The migrated configuration dict.
        """
        return old_config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """Raise if the plugin has not been initialised.

        Call at the top of methods that depend on :attr:`_ctx`.

        Raises:
            RuntimeError: If :meth:`initialize` has not been called.
        """
        if not self._initialized:
            raise RuntimeError(
                f"Plugin '{self.plugin_name}' is not initialised."
            )
