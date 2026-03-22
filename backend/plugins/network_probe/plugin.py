"""AL\\CE — Network probe plugin.

Exposes LAN diagnostic tools: ICMP ping, TCP port scan, service
banner checks, ARP-based device discovery, local interface info,
traceroute, DNS resolution, and active connection listing.
All targets are validated to be RFC-1918 / loopback only.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.network_probe.prober import NetworkProber
from backend.plugins.network_probe.validator import (
    LocalNetworkValidationError,
    async_validate_host_local,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


class NetworkProbePlugin(BasePlugin):
    """LAN diagnostics plugin for AL\\CE."""

    plugin_name: str = "network_probe"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Provides LAN diagnostics: ping, traceroute, port scan, service "
        "checks, DNS resolution, device discovery, active connections "
        "and local network information."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 45

    def __init__(self) -> None:
        super().__init__()
        self._prober: NetworkProber | None = None

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Initialize the plugin and create the network prober.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        self._prober = NetworkProber(ctx.config.network_probe)
        logger.info("NetworkProbePlugin initialized")

    async def cleanup(self) -> None:
        """Release prober resources."""
        self._prober = None
        await super().cleanup()

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for network probe operations.

        Returns:
            A list of eight ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="ping_host",
                description=(
                    "Send ICMP echo requests to a local network host and "
                    "return latency statistics (min/avg/max, loss %)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": (
                                "Target IP address or hostname "
                                "(must be on the local network)."
                            ),
                        },
                        "count": {
                            "type": "integer",
                            "description": (
                                "Number of ICMP packets to send."
                            ),
                            "default": 4,
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["host"],
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=30_000,
            ),
            ToolDefinition(
                name="scan_ports",
                description=(
                    "Scan a list of TCP ports on a local network host and "
                    "report which are open or closed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": (
                                "Target IP address or hostname "
                                "(must be on the local network)."
                            ),
                        },
                        "ports": {
                            "type": "array",
                            "description": "List of TCP port numbers to scan.",
                            "items": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 65535,
                            },
                            "maxItems": 100,
                        },
                        "timeout_s": {
                            "type": "number",
                            "description": (
                                "Per-port TCP connect timeout in seconds."
                            ),
                            "default": 1.0,
                            "minimum": 0.1,
                            "maximum": 10.0,
                        },
                    },
                    "required": ["host", "ports"],
                },
                result_type="json",
                risk_level="medium",
                timeout_ms=60_000,
            ),
            ToolDefinition(
                name="check_service",
                description=(
                    "Check if a specific service (HTTP, HTTPS, SSH, FTP) "
                    "is running on a local network host and port."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": (
                                "Target IP address or hostname "
                                "(must be on the local network)."
                            ),
                        },
                        "port": {
                            "type": "integer",
                            "description": "TCP port of the service.",
                            "minimum": 1,
                            "maximum": 65535,
                        },
                        "protocol": {
                            "type": "string",
                            "description": "Service protocol to check.",
                            "enum": ["http", "https", "ssh", "ftp"],
                        },
                    },
                    "required": ["host", "port", "protocol"],
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="discover_local_devices",
                description=(
                    "Discover devices on the local network via ARP scan. "
                    "Returns IP, MAC address and hostname for each device."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="medium",
                timeout_ms=90_000,
                max_result_chars=20_000,
            ),
            ToolDefinition(
                name="get_local_network_info",
                description=(
                    "Return local network information: hostname, default "
                    "gateway, DNS servers and network interfaces."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="safe",
                timeout_ms=10_000,
            ),
            ToolDefinition(
                name="traceroute_host",
                description=(
                    "Trace the network path to a local host, showing "
                    "each hop with its IP and round-trip time."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": (
                                "Target IP address or hostname "
                                "(must be on the local network)."
                            ),
                        },
                        "max_hops": {
                            "type": "integer",
                            "description": "Maximum number of hops.",
                            "default": 15,
                            "minimum": 1,
                            "maximum": 30,
                        },
                    },
                    "required": ["host"],
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=60_000,
            ),
            ToolDefinition(
                name="resolve_hostname",
                description=(
                    "Resolve a hostname to IP addresses (forward lookup) "
                    "or an IP address to a hostname (reverse lookup)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Hostname for forward DNS lookup, or "
                                "IP address for reverse DNS lookup."
                            ),
                        },
                    },
                    "required": ["query"],
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=10_000,
            ),
            ToolDefinition(
                name="get_open_connections",
                description=(
                    "List active network connections on this machine: "
                    "local/remote address, port, protocol, status, "
                    "and owning process."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "protocol": {
                            "type": "string",
                            "description": "Filter by protocol.",
                            "enum": ["tcp", "udp", "all"],
                            "default": "tcp",
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=10_000,
                max_result_chars=20_000,
            ),
        ]

    # -- Dispatch ----------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested network probe tool.

        Args:
            tool_name: One of the eight registered tool names.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the JSON payload or an error.
        """
        if self._prober is None:
            return ToolResult.error("NetworkProbePlugin not initialized")

        start = time.perf_counter()

        try:
            match tool_name:
                case "ping_host":
                    return await self._handle_ping_host(args, start)
                case "scan_ports":
                    return await self._handle_scan_ports(args, start)
                case "check_service":
                    return await self._handle_check_service(args, start)
                case "discover_local_devices":
                    return await self._handle_discover(start)
                case "get_local_network_info":
                    return await self._handle_netinfo(start)
                case "traceroute_host":
                    return await self._handle_traceroute(args, start)
                case "resolve_hostname":
                    return await self._handle_resolve(args, start)
                case "get_open_connections":
                    return await self._handle_connections(args, start)
                case _:
                    return ToolResult.error(f"Unknown tool: {tool_name}")
        except LocalNetworkValidationError as exc:
            return ToolResult.error(str(exc))
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ToolResult.error(
                f"Tool {tool_name} timed out after {elapsed_ms:.0f}ms"
            )
        except Exception as exc:
            self.logger.error("Tool {} failed: {}", tool_name, exc)
            return ToolResult.error(
                str(exc) or f"Tool {tool_name} failed: {type(exc).__name__}"
            )

    # -- Private handlers --------------------------------------------------

    async def _handle_ping_host(
        self, args: dict[str, Any], start: float
    ) -> ToolResult:
        """Validate host and execute ping."""
        host: str = args["host"]
        count: int = args.get("count", 4)
        await async_validate_host_local(host)
        result = await self._prober.ping_host(host, count)  # type: ignore[union-attr]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=asdict(result),
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_scan_ports(
        self, args: dict[str, Any], start: float
    ) -> ToolResult:
        """Validate host and scan TCP ports."""
        host: str = args["host"]
        ports: list[int] = args["ports"]
        cfg = self.ctx.config.network_probe
        timeout_s: float = args.get("timeout_s", cfg.port_scan_timeout_s)

        if not ports:
            return ToolResult.error("ports list must not be empty")
        if len(ports) > cfg.max_ports_per_scan:
            return ToolResult.error(
                f"ports list exceeds {cfg.max_ports_per_scan} entries"
            )

        await async_validate_host_local(host)
        results = await self._prober.scan_ports(host, ports, timeout_s)  # type: ignore[union-attr]

        open_ports = [asdict(r) for r in results if r.open]
        closed_ports = [asdict(r) for r in results if not r.open]
        elapsed_ms = (time.perf_counter() - start) * 1000

        return ToolResult.ok(
            content={
                "host": host,
                "open": open_ports,
                "closed": closed_ports,
                "total_scanned": len(results),
            },
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_check_service(
        self, args: dict[str, Any], start: float
    ) -> ToolResult:
        """Validate host and check a specific service."""
        host: str = args["host"]
        port: int = args["port"]
        protocol: str = args["protocol"]
        await async_validate_host_local(host)
        result = await self._prober.check_service(host, port, protocol)  # type: ignore[union-attr]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=asdict(result),
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_discover(self, start: float) -> ToolResult:
        """Discover devices on the local network."""
        timeout = self.ctx.config.network_probe.discover_timeout_s
        devices = await asyncio.wait_for(
            self._prober.discover_local_devices(),  # type: ignore[union-attr]
            timeout=timeout,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={
                "count": len(devices),
                "devices": [asdict(d) for d in devices],
            },
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_netinfo(self, start: float) -> ToolResult:
        """Collect local network interface information."""
        info = await self._prober.get_local_network_info()  # type: ignore[union-attr]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={
                "hostname": info.hostname,
                "gateway": info.gateway,
                "dns_servers": info.dns_servers,
                "interfaces": [asdict(i) for i in info.interfaces],
            },
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_traceroute(
        self, args: dict[str, Any], start: float
    ) -> ToolResult:
        """Validate host and run traceroute."""
        host: str = args["host"]
        max_hops: int = args.get("max_hops", 15)
        await async_validate_host_local(host)
        result = await self._prober.traceroute_host(host, max_hops)  # type: ignore[union-attr]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=asdict(result),
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_resolve(
        self, args: dict[str, Any], start: float
    ) -> ToolResult:
        """Perform DNS forward or reverse lookup."""
        query: str = args["query"]
        result = await self._prober.resolve_hostname(query)  # type: ignore[union-attr]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=asdict(result),
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_connections(
        self, args: dict[str, Any], start: float
    ) -> ToolResult:
        """List active network connections."""
        protocol: str = args.get("protocol", "tcp")
        connections = await self._prober.get_open_connections(protocol)  # type: ignore[union-attr]
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={
                "count": len(connections),
                "connections": [asdict(c) for c in connections],
            },
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    # -- Health ------------------------------------------------------------

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if prober is available, ERROR otherwise.

        Returns:
            ``ConnectionStatus.CONNECTED`` or ``ConnectionStatus.ERROR``.
        """
        if self._prober is not None:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR
