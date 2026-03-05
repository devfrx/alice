"""O.M.N.I.A. — System Info plugin.

Exposes ``get_system_info`` and ``get_process_list`` tools that report
hardware/OS metrics via *psutil*.  All output is strictly whitelisted
to avoid leaking private data (hostnames, user paths, env vars).
"""

from __future__ import annotations

import asyncio
import platform
import time
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

# -- Lazy import of psutil ------------------------------------------------

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

# -- Constants ------------------------------------------------------------

_BYTES_PER_GB = 1 << 30

_SYSTEM_INFO_FIELDS: set[str] = {
    "cpu_percent",
    "cpu_count",
    "ram_total_gb",
    "ram_used_gb",
    "ram_percent",
    "disk_total_gb",
    "disk_used_gb",
    "disk_percent",
    "os_name",
    "os_version",
    "os_architecture",
    "python_version",
    "boot_time",
}

_PROCESS_FIELDS: set[str] = {"pid", "name", "cpu_percent", "memory_percent", "status"}


# -- Plugin ----------------------------------------------------------------


class SystemInfoPlugin(BasePlugin):
    """Reports system metrics through safe, whitelisted tools."""

    plugin_name: str = "system_info"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Provides CPU, RAM, disk and OS information plus a filtered process list."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 50

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for system info and process list.

        Returns:
            A list of two ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="get_system_info",
                description=(
                    "Return CPU usage, RAM usage, disk usage, OS details "
                    "and Python version. No private data is included."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="safe",
                timeout_ms=10000,
            ),
            ToolDefinition(
                name="get_process_list",
                description=(
                    "Return a filtered list of running processes with name, "
                    "pid, cpu_percent, memory_percent and status. "
                    "Optionally filter by process name substring."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "filter_name": {
                            "type": "string",
                            "description": "Substring to filter process names (case-insensitive).",
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=10000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested tool.

        Args:
            tool_name: ``"get_system_info"`` or ``"get_process_list"``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the JSON payload or an error.
        """
        if not _PSUTIL_AVAILABLE:
            return ToolResult.error("psutil not installed")

        start = time.perf_counter()

        if tool_name == "get_system_info":
            data = await asyncio.to_thread(self._collect_system_info)
        elif tool_name == "get_process_list":
            filter_name: str | None = args.get("filter_name")
            data = await asyncio.to_thread(self._collect_process_list, filter_name)
        else:
            return ToolResult.error(f"Unknown tool: {tool_name}")

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=data,
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    # -- Dependency / health -----------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list with ``"psutil"`` if the package is not installed,
            otherwise an empty list.
        """
        if not _PSUTIL_AVAILABLE:
            return ["psutil"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if psutil is available, DEGRADED otherwise.

        Returns:
            ``ConnectionStatus.CONNECTED`` or ``ConnectionStatus.DEGRADED``.
        """
        if _PSUTIL_AVAILABLE:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.DEGRADED

    # -- Private helpers ---------------------------------------------------

    def _collect_system_info(self) -> dict[str, Any]:
        """Gather whitelisted system metrics.

        Returns:
            A dict containing only the fields in ``_SYSTEM_INFO_FIELDS``.
        """
        assert psutil is not None  # guarded by execute_tool

        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot_ts = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc).isoformat()

        data: dict[str, Any] = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_gb": round(vm.total / _BYTES_PER_GB, 2),
            "ram_used_gb": round(vm.used / _BYTES_PER_GB, 2),
            "ram_percent": vm.percent,
            "disk_total_gb": round(disk.total / _BYTES_PER_GB, 2),
            "disk_used_gb": round(disk.used / _BYTES_PER_GB, 2),
            "disk_percent": disk.percent,
            "os_name": platform.system(),
            "os_version": platform.version(),
            "os_architecture": platform.machine(),
            "python_version": platform.python_version(),
            "boot_time": boot_ts,
        }

        # Enforce whitelist — strip anything unexpected
        return {k: v for k, v in data.items() if k in _SYSTEM_INFO_FIELDS}

    def _collect_process_list(
        self,
        filter_name: str | None = None,
    ) -> dict[str, Any]:
        """Gather a filtered process list with whitelisted fields only.

        Args:
            filter_name: Optional case-insensitive substring to match
                against process names.

        Returns:
            A dict with ``"processes"`` key containing the list.
        """
        assert psutil is not None  # guarded by execute_tool

        processes: list[dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = proc.info  # type: ignore[attr-defined]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            # Apply name filter if provided
            proc_name: str = info.get("name") or ""
            if filter_name and filter_name.lower() not in proc_name.lower():
                continue

            # Enforce whitelist
            entry = {k: info[k] for k in _PROCESS_FIELDS if k in info}
            processes.append(entry)

        return {"processes": processes}


# -- Register in static registry ------------------------------------------

PLUGIN_REGISTRY["system_info"] = SystemInfoPlugin
