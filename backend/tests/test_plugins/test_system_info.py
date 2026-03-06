"""Tests for the system_info plugin.

All ``psutil`` calls are mocked so the tests are portable and
deterministic.  Covers tool definitions, output schemas, whitelist
enforcement, dependency checking, and connection status.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
)

# -- Fixtures --------------------------------------------------------------

_EXEC_CTX = ExecutionContext(
    session_id="sess-1",
    conversation_id="conv-1",
    execution_id="exec-1",
)


def _make_virtual_memory() -> SimpleNamespace:
    """Fake psutil.virtual_memory() return value."""
    gb = 1 << 30
    return SimpleNamespace(total=16 * gb, used=8 * gb, percent=50.0)


def _make_disk_usage(_path: str = "/") -> SimpleNamespace:
    """Fake psutil.disk_usage() return value."""
    gb = 1 << 30
    return SimpleNamespace(total=500 * gb, used=250 * gb, percent=50.0)


def _make_process_iter(_attrs: list[str] | None = None) -> list[MagicMock]:
    """Return a list of fake process objects."""
    entries = [
        {"pid": 1, "name": "systemd", "cpu_percent": 0.1, "memory_percent": 0.5, "status": "running"},
        {"pid": 100, "name": "python", "cpu_percent": 5.0, "memory_percent": 2.0, "status": "running"},
        {"pid": 200, "name": "chrome", "cpu_percent": 10.0, "memory_percent": 8.0, "status": "running"},
    ]
    mocks = []
    for entry in entries:
        proc = MagicMock()
        proc.info = entry
        mocks.append(proc)
    return mocks


@pytest.fixture
def plugin():
    """Return an uninitialized SystemInfoPlugin with psutil available."""
    # Import here so the module-level lazy import has already happened
    from backend.plugins.system_info.plugin import SystemInfoPlugin

    return SystemInfoPlugin()


# -- Tool definitions -------------------------------------------------------


class TestGetTools:
    """Verify tool definitions returned by the plugin."""

    def test_returns_two_tools(self, plugin) -> None:
        tools = plugin.get_tools()
        assert len(tools) == 2

    def test_tool_types(self, plugin) -> None:
        tools = plugin.get_tools()
        for tool in tools:
            assert isinstance(tool, ToolDefinition)

    def test_get_system_info_definition(self, plugin) -> None:
        tools = {t.name: t for t in plugin.get_tools()}
        t = tools["get_system_info"]
        assert t.result_type == "json"
        assert t.risk_level == "safe"
        assert t.timeout_ms == 10000

    def test_get_process_list_definition(self, plugin) -> None:
        tools = {t.name: t for t in plugin.get_tools()}
        t = tools["get_process_list"]
        assert t.result_type == "json"
        assert t.risk_level == "safe"
        assert "filter_name" in t.parameters["properties"]


# -- get_system_info --------------------------------------------------------


class TestGetSystemInfo:
    """Test the get_system_info tool execution."""

    @pytest.mark.asyncio
    async def test_returns_expected_keys(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.cpu_count.return_value = 8
            mock_psutil.virtual_memory.return_value = _make_virtual_memory()
            mock_psutil.disk_usage.return_value = _make_disk_usage()
            mock_psutil.boot_time.return_value = 1700000000.0

            result = await plugin.execute_tool("get_system_info", {}, _EXEC_CTX)

        assert result.success is True
        data = result.content
        expected_keys = {
            "cpu_percent", "cpu_count",
            "ram_total_gb", "ram_used_gb", "ram_percent",
            "disk_total_gb", "disk_used_gb", "disk_percent",
            "os_name", "os_version", "os_architecture",
            "python_version", "boot_time",
        }
        assert set(data.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_values_are_reasonable(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.cpu_count.return_value = 8
            mock_psutil.virtual_memory.return_value = _make_virtual_memory()
            mock_psutil.disk_usage.return_value = _make_disk_usage()
            mock_psutil.boot_time.return_value = 1700000000.0

            result = await plugin.execute_tool("get_system_info", {}, _EXEC_CTX)

        data = result.content
        assert data["cpu_percent"] == 25.0
        assert data["cpu_count"] == 8
        assert data["ram_total_gb"] == 16.0
        assert data["ram_percent"] == 50.0

    @pytest.mark.asyncio
    async def test_whitelist_no_private_data(self, plugin) -> None:
        """Output must NOT contain user paths, hostnames, or env vars."""
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = _make_virtual_memory()
            mock_psutil.disk_usage.return_value = _make_disk_usage()
            mock_psutil.boot_time.return_value = 1700000000.0

            result = await plugin.execute_tool("get_system_info", {}, _EXEC_CTX)

        data = result.content
        forbidden_keys = {"hostname", "username", "user", "env", "environment", "home", "path"}
        assert forbidden_keys.isdisjoint(set(data.keys()))

    @pytest.mark.asyncio
    async def test_content_type_is_json(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = _make_virtual_memory()
            mock_psutil.disk_usage.return_value = _make_disk_usage()
            mock_psutil.boot_time.return_value = 1700000000.0

            result = await plugin.execute_tool("get_system_info", {}, _EXEC_CTX)

        assert result.content_type == "application/json"


# -- get_process_list -------------------------------------------------------


class TestGetProcessList:
    """Test the get_process_list tool execution."""

    @pytest.mark.asyncio
    async def test_returns_process_list(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.process_iter.return_value = _make_process_iter()
            mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
            mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

            result = await plugin.execute_tool("get_process_list", {}, _EXEC_CTX)

        assert result.success is True
        procs = result.content["processes"]
        assert len(procs) == 3

    @pytest.mark.asyncio
    async def test_process_fields_are_whitelisted(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.process_iter.return_value = _make_process_iter()
            mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
            mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

            result = await plugin.execute_tool("get_process_list", {}, _EXEC_CTX)

        allowed = {"pid", "name", "cpu_percent", "memory_percent", "status"}
        for proc in result.content["processes"]:
            assert set(proc.keys()) <= allowed

    @pytest.mark.asyncio
    async def test_filter_name(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.process_iter.return_value = _make_process_iter()
            mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
            mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

            result = await plugin.execute_tool(
                "get_process_list", {"filter_name": "python"}, _EXEC_CTX,
            )

        procs = result.content["processes"]
        assert len(procs) == 1
        assert procs[0]["name"] == "python"

    @pytest.mark.asyncio
    async def test_filter_name_case_insensitive(self, plugin) -> None:
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.process_iter.return_value = _make_process_iter()
            mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
            mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

            result = await plugin.execute_tool(
                "get_process_list", {"filter_name": "CHROME"}, _EXEC_CTX,
            )

        procs = result.content["processes"]
        assert len(procs) == 1
        assert procs[0]["name"] == "chrome"

    @pytest.mark.asyncio
    async def test_no_private_fields_in_processes(self, plugin) -> None:
        """Process entries must not contain exe paths, cmdline, environ, etc."""
        with (
            patch("backend.plugins.system_info.plugin.psutil") as mock_psutil,
            patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.process_iter.return_value = _make_process_iter()
            mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
            mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

            result = await plugin.execute_tool("get_process_list", {}, _EXEC_CTX)

        forbidden = {"exe", "cmdline", "environ", "cwd", "username", "open_files"}
        for proc in result.content["processes"]:
            assert forbidden.isdisjoint(set(proc.keys()))


# -- Dependency / health ----------------------------------------------------


class TestDependencies:
    """Test check_dependencies and get_connection_status."""

    def test_check_dependencies_with_psutil(self, plugin) -> None:
        with patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True):
            assert plugin.check_dependencies() == []

    def test_check_dependencies_without_psutil(self, plugin) -> None:
        with patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", False):
            missing = plugin.check_dependencies()
            assert "psutil" in missing

    @pytest.mark.asyncio
    async def test_connection_status_connected(self, plugin) -> None:
        with patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True):
            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_connection_status_degraded(self, plugin) -> None:
        with patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", False):
            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.DISCONNECTED


# -- Error paths ------------------------------------------------------------


class TestErrorPaths:
    """Test error handling for edge cases."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, plugin) -> None:
        with patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", True):
            result = await plugin.execute_tool("nonexistent_tool", {}, _EXEC_CTX)
        assert result.success is False
        assert "Unknown tool" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_psutil_missing_returns_error(self, plugin) -> None:
        with patch("backend.plugins.system_info.plugin._PSUTIL_AVAILABLE", False):
            result = await plugin.execute_tool("get_system_info", {}, _EXEC_CTX)
        assert result.success is False
        assert "psutil not installed" in (result.error_message or "")


# -- Plugin metadata --------------------------------------------------------


class TestPluginMetadata:
    """Verify plugin class attributes."""

    def test_plugin_name(self, plugin) -> None:
        assert plugin.plugin_name == "system_info"

    def test_plugin_version(self, plugin) -> None:
        assert plugin.plugin_version == "1.0.0"

    def test_plugin_registered(self) -> None:
        from backend.core.plugin_manager import PLUGIN_REGISTRY
        from backend.plugins.system_info.plugin import SystemInfoPlugin

        assert PLUGIN_REGISTRY.get("system_info") is SystemInfoPlugin
