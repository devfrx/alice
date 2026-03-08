"""Tests for backend.plugins.media_control — MediaControlPlugin & executor."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_app_context() -> AppContext:
    """Build a minimal AppContext with default config."""
    return AppContext(
        config=load_config(),
        event_bus=EventBus(),
        db=None,
    )


def _mock_volume_interface(
    *,
    scalar: float = 0.5,
    muted: bool = False,
) -> MagicMock:
    """Return a mock IAudioEndpointVolume COM interface."""
    vol = MagicMock()
    vol.GetMasterVolumeLevelScalar.return_value = scalar
    vol.GetMute.return_value = muted
    vol.SetMasterVolumeLevelScalar = MagicMock()
    vol.SetMute = MagicMock()
    return vol


# ===========================================================================
# 1. Plugin lifecycle
# ===========================================================================


class TestMediaControlPluginLifecycle:
    """Verify plugin attributes and lifecycle behaviour."""

    def test_plugin_attributes(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        assert plugin.plugin_name == "media_control"
        assert plugin.plugin_priority == 30
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_dependencies == []

    @pytest.mark.asyncio
    async def test_initialize_sets_ctx(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        assert plugin.is_initialized
        assert plugin.ctx is ctx

    def test_tool_count(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        tools = plugin.get_tools()
        assert len(tools) == 10

    def test_tool_names(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        names = {t.name for t in plugin.get_tools()}
        assert names == {
            "get_volume",
            "set_volume",
            "volume_up",
            "volume_down",
            "mute",
            "unmute",
            "media_play_pause",
            "media_next",
            "media_previous",
            "set_brightness",
        }

    def test_tool_risk_levels(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        risk = {t.name: t.risk_level for t in plugin.get_tools()}

        for name in (
            "get_volume", "volume_up", "volume_down",
            "mute", "unmute",
            "media_play_pause", "media_next", "media_previous",
        ):
            assert risk[name] == "safe", f"{name} should be safe"

        assert risk["set_volume"] == "medium"
        assert risk["set_brightness"] == "medium"

    def test_check_dependencies_all_present(self):
        from backend.plugins.media_control import executor as exec_mod
        from backend.plugins.media_control.plugin import MediaControlPlugin

        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        orig_win32 = exec_mod._WIN32_AVAILABLE
        try:
            exec_mod._PYCAW_AVAILABLE = True
            exec_mod._WIN32_AVAILABLE = True
            plugin = MediaControlPlugin()
            assert plugin.check_dependencies() == []
        finally:
            exec_mod._PYCAW_AVAILABLE = orig_pycaw
            exec_mod._WIN32_AVAILABLE = orig_win32

    def test_check_dependencies_pycaw_missing(self):
        from backend.plugins.media_control import executor as exec_mod
        from backend.plugins.media_control.plugin import MediaControlPlugin

        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        orig_win32 = exec_mod._WIN32_AVAILABLE
        try:
            exec_mod._PYCAW_AVAILABLE = False
            exec_mod._WIN32_AVAILABLE = True
            plugin = MediaControlPlugin()
            assert "pycaw" in plugin.check_dependencies()
        finally:
            exec_mod._PYCAW_AVAILABLE = orig_pycaw
            exec_mod._WIN32_AVAILABLE = orig_win32

    def test_check_dependencies_all_missing(self):
        from backend.plugins.media_control import executor as exec_mod
        from backend.plugins.media_control.plugin import MediaControlPlugin

        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        orig_win32 = exec_mod._WIN32_AVAILABLE
        try:
            exec_mod._PYCAW_AVAILABLE = False
            exec_mod._WIN32_AVAILABLE = False
            plugin = MediaControlPlugin()
            deps = plugin.check_dependencies()
            assert "pycaw" in deps
            assert "pywin32" in deps
        finally:
            exec_mod._PYCAW_AVAILABLE = orig_pycaw
            exec_mod._WIN32_AVAILABLE = orig_win32

    @pytest.mark.asyncio
    async def test_connection_status_connected(self):
        from backend.plugins.media_control import executor as exec_mod
        from backend.plugins.media_control.plugin import MediaControlPlugin

        orig_is_win = exec_mod._IS_WINDOWS
        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        orig_win32 = exec_mod._WIN32_AVAILABLE
        try:
            exec_mod._IS_WINDOWS = True
            exec_mod._PYCAW_AVAILABLE = True
            exec_mod._WIN32_AVAILABLE = True

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.CONNECTED
        finally:
            exec_mod._IS_WINDOWS = orig_is_win
            exec_mod._PYCAW_AVAILABLE = orig_pycaw
            exec_mod._WIN32_AVAILABLE = orig_win32

    @pytest.mark.asyncio
    async def test_connection_status_degraded(self):
        from backend.plugins.media_control import executor as exec_mod
        from backend.plugins.media_control import plugin as plugin_mod
        from backend.plugins.media_control.plugin import MediaControlPlugin

        orig_is_win = exec_mod._IS_WINDOWS
        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        orig_win32 = exec_mod._WIN32_AVAILABLE
        orig_plug_is_win = plugin_mod._IS_WINDOWS
        try:
            exec_mod._IS_WINDOWS = True
            plugin_mod._IS_WINDOWS = True
            exec_mod._PYCAW_AVAILABLE = True
            exec_mod._WIN32_AVAILABLE = False

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.DEGRADED
        finally:
            exec_mod._IS_WINDOWS = orig_is_win
            exec_mod._PYCAW_AVAILABLE = orig_pycaw
            exec_mod._WIN32_AVAILABLE = orig_win32
            plugin_mod._IS_WINDOWS = orig_plug_is_win

    @pytest.mark.asyncio
    async def test_connection_status_error_not_windows(self):
        from backend.plugins.media_control import plugin as plugin_mod
        from backend.plugins.media_control.plugin import MediaControlPlugin

        orig = plugin_mod._IS_WINDOWS
        try:
            plugin_mod._IS_WINDOWS = False

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.ERROR
        finally:
            plugin_mod._IS_WINDOWS = orig

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool("nonexistent", {}, _make_exec_ctx())
        assert not result.success
        assert "Unknown tool" in result.error_message


# ===========================================================================
# 2. Volume tools
# ===========================================================================


class TestVolumeTools:
    """Test get_volume, set_volume, volume_up, volume_down, mute, unmute."""

    @pytest.mark.asyncio
    async def test_get_volume(self):
        vol_iface = _mock_volume_interface(scalar=0.75)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("get_volume", {}, _make_exec_ctx())

        assert result.success
        assert "75%" in result.content

    @pytest.mark.asyncio
    async def test_get_volume_zero(self):
        vol_iface = _mock_volume_interface(scalar=0.0)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("get_volume", {}, _make_exec_ctx())

        assert result.success
        assert "0%" in result.content

    @pytest.mark.asyncio
    async def test_get_volume_full(self):
        vol_iface = _mock_volume_interface(scalar=1.0)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("get_volume", {}, _make_exec_ctx())

        assert result.success
        assert "100%" in result.content

    @pytest.mark.asyncio
    async def test_set_volume_valid(self):
        vol_iface = _mock_volume_interface()

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_volume", {"level": 42}, _make_exec_ctx(),
            )

        assert result.success
        assert "42%" in result.content
        vol_iface.SetMasterVolumeLevelScalar.assert_called_once_with(0.42, None)

    @pytest.mark.asyncio
    async def test_set_volume_zero(self):
        vol_iface = _mock_volume_interface()

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_volume", {"level": 0}, _make_exec_ctx(),
            )

        assert result.success
        vol_iface.SetMasterVolumeLevelScalar.assert_called_once_with(0.0, None)

    @pytest.mark.asyncio
    async def test_set_volume_100(self):
        vol_iface = _mock_volume_interface()

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_volume", {"level": 100}, _make_exec_ctx(),
            )

        assert result.success
        vol_iface.SetMasterVolumeLevelScalar.assert_called_once_with(1.0, None)

    @pytest.mark.asyncio
    async def test_set_volume_out_of_range_high(self):
        """Volume > 100 → ValueError → error ToolResult."""
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "set_volume", {"level": 150}, _make_exec_ctx(),
        )

        assert not result.success
        assert "0–100" in result.error_message or "0-100" in result.error_message

    @pytest.mark.asyncio
    async def test_set_volume_out_of_range_negative(self):
        from backend.plugins.media_control.plugin import MediaControlPlugin

        plugin = MediaControlPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "set_volume", {"level": -5}, _make_exec_ctx(),
        )

        assert not result.success

    @pytest.mark.asyncio
    async def test_volume_up(self):
        """volume_up reads current, adds step, calls set_volume."""
        vol_iface = _mock_volume_interface(scalar=0.5)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("volume_up", {}, _make_exec_ctx())

        assert result.success
        # 50 + 10 (default step) = 60
        assert "60%" in result.content
        vol_iface.SetMasterVolumeLevelScalar.assert_called_once_with(0.6, None)

    @pytest.mark.asyncio
    async def test_volume_up_clamps_at_100(self):
        vol_iface = _mock_volume_interface(scalar=0.95)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("volume_up", {}, _make_exec_ctx())

        assert result.success
        assert "100%" in result.content

    @pytest.mark.asyncio
    async def test_volume_down(self):
        vol_iface = _mock_volume_interface(scalar=0.5)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("volume_down", {}, _make_exec_ctx())

        assert result.success
        # 50 - 10 = 40
        assert "40%" in result.content
        vol_iface.SetMasterVolumeLevelScalar.assert_called_once_with(0.4, None)

    @pytest.mark.asyncio
    async def test_volume_down_clamps_at_0(self):
        vol_iface = _mock_volume_interface(scalar=0.05)

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("volume_down", {}, _make_exec_ctx())

        assert result.success
        assert "0%" in result.content

    @pytest.mark.asyncio
    async def test_mute(self):
        vol_iface = _mock_volume_interface()

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("mute", {}, _make_exec_ctx())

        assert result.success
        assert "muted" in result.content.lower()
        vol_iface.SetMute.assert_called_once_with(True, None)

    @pytest.mark.asyncio
    async def test_unmute(self):
        vol_iface = _mock_volume_interface()

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("unmute", {}, _make_exec_ctx())

        assert result.success
        assert "unmuted" in result.content.lower()
        vol_iface.SetMute.assert_called_once_with(False, None)

    @pytest.mark.asyncio
    async def test_set_volume_float_coercion(self):
        """LLM may send 50.0 (float) instead of 50 (int) — should work."""
        vol_iface = _mock_volume_interface()

        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            return_value=vol_iface,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_volume", {"level": 50.0}, _make_exec_ctx(),
            )

        assert result.success
        assert "50%" in result.content
        vol_iface.SetMasterVolumeLevelScalar.assert_called_once_with(0.5, None)

    @pytest.mark.asyncio
    async def test_set_brightness_float_coercion(self):
        """LLM may send 70.0 (float) instead of 70 (int) — should work."""
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ), patch(
            "backend.plugins.media_control.executor.subprocess.run",
            return_value=completed,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 70.0}, _make_exec_ctx(),
            )

        assert result.success
        assert "70%" in result.content


# ===========================================================================
# 3. Media key tools
# ===========================================================================


class TestMediaKeys:
    """Test play_pause, next, previous through mocked win32api."""

    @pytest.mark.asyncio
    async def test_media_play_pause(self):
        with patch(
            "backend.plugins.media_control.executor._send_media_key",
            return_value="Media key sent: play/pause",
        ) as mock_send:
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "media_play_pause", {}, _make_exec_ctx(),
            )

        assert result.success
        assert "play/pause" in result.content
        mock_send.assert_called_once_with(0xB3, "play/pause")

    @pytest.mark.asyncio
    async def test_media_next(self):
        with patch(
            "backend.plugins.media_control.executor._send_media_key",
            return_value="Media key sent: next track",
        ) as mock_send:
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "media_next", {}, _make_exec_ctx(),
            )

        assert result.success
        assert "next" in result.content.lower()
        mock_send.assert_called_once_with(0xB0, "next track")

    @pytest.mark.asyncio
    async def test_media_previous(self):
        with patch(
            "backend.plugins.media_control.executor._send_media_key",
            return_value="Media key sent: previous track",
        ) as mock_send:
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "media_previous", {}, _make_exec_ctx(),
            )

        assert result.success
        assert "previous" in result.content.lower()
        mock_send.assert_called_once_with(0xB1, "previous track")

    @pytest.mark.asyncio
    async def test_media_key_runtime_error(self):
        """If _send_media_key raises RuntimeError the plugin returns error."""
        with patch(
            "backend.plugins.media_control.executor._send_media_key",
            side_effect=RuntimeError("pywin32 is not installed"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "media_play_pause", {}, _make_exec_ctx(),
            )

        assert not result.success
        assert "pywin32" in result.error_message


# ===========================================================================
# 4. Brightness tool
# ===========================================================================


class TestBrightnessTool:
    """Test set_brightness via mocked subprocess."""

    @pytest.mark.asyncio
    async def test_set_brightness_valid(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ), patch(
            "backend.plugins.media_control.executor.subprocess.run",
            return_value=completed,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 70}, _make_exec_ctx(),
            )

        assert result.success
        assert "70%" in result.content

    @pytest.mark.asyncio
    async def test_set_brightness_zero(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ), patch(
            "backend.plugins.media_control.executor.subprocess.run",
            return_value=completed,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 0}, _make_exec_ctx(),
            )

        assert result.success

    @pytest.mark.asyncio
    async def test_set_brightness_100(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ), patch(
            "backend.plugins.media_control.executor.subprocess.run",
            return_value=completed,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 100}, _make_exec_ctx(),
            )

        assert result.success
        assert "100%" in result.content

    @pytest.mark.asyncio
    async def test_set_brightness_out_of_range(self):
        """Brightness > 100 → ValueError → error result."""
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 150}, _make_exec_ctx(),
            )

        assert not result.success
        assert "0–100" in result.error_message or "0-100" in result.error_message

    @pytest.mark.asyncio
    async def test_set_brightness_negative(self):
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": -10}, _make_exec_ctx(),
            )

        assert not result.success

    @pytest.mark.asyncio
    async def test_set_brightness_monitor_not_supported(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="The method is not supported on this monitor",
        )
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ), patch(
            "backend.plugins.media_control.executor.subprocess.run",
            return_value=completed,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 50}, _make_exec_ctx(),
            )

        assert not result.success
        assert "not support" in result.error_message.lower() or "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_set_brightness_powershell_error(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="Some random powershell error",
        )
        with patch(
            "backend.plugins.media_control.executor.check_platform",
        ), patch(
            "backend.plugins.media_control.executor.subprocess.run",
            return_value=completed,
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 50}, _make_exec_ctx(),
            )

        assert not result.success
        assert "failed" in result.error_message.lower()


# ===========================================================================
# 5. Non-Windows platform
# ===========================================================================


class TestNonWindows:
    """Verify that all tools fail gracefully when not on Windows."""

    @pytest.mark.asyncio
    async def test_set_brightness_not_windows(self):
        """set_brightness calls check_platform → RuntimeError."""
        with patch(
            "backend.plugins.media_control.executor._IS_WINDOWS", False,
        ), patch(
            "backend.plugins.media_control.executor.check_platform",
            side_effect=RuntimeError("Media control is Windows-only"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_brightness", {"level": 50}, _make_exec_ctx(),
            )

        assert not result.success
        assert "Windows" in result.error_message

    @pytest.mark.asyncio
    async def test_volume_tools_not_windows(self):
        """Volume tools call _get_volume_interface → check_platform → RuntimeError."""
        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            side_effect=RuntimeError("Media control is Windows-only"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            for tool_name in ("get_volume", "mute", "unmute"):
                result = await plugin.execute_tool(tool_name, {}, _make_exec_ctx())
                assert not result.success, f"{tool_name} should fail"
                assert "Windows" in result.error_message

    @pytest.mark.asyncio
    async def test_set_volume_not_windows(self):
        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            side_effect=RuntimeError("Media control is Windows-only"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "set_volume", {"level": 50}, _make_exec_ctx(),
            )
            assert not result.success

    @pytest.mark.asyncio
    async def test_media_keys_not_windows(self):
        with patch(
            "backend.plugins.media_control.executor._send_media_key",
            side_effect=RuntimeError("Media control is Windows-only"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            for tool_name in ("media_play_pause", "media_next", "media_previous"):
                result = await plugin.execute_tool(tool_name, {}, _make_exec_ctx())
                assert not result.success, f"{tool_name} should fail"


# ===========================================================================
# 6. COM edge cases
# ===========================================================================


class TestComEdgeCases:
    """Test COM device disconnection / reinitialisation and exceptions."""

    @pytest.mark.asyncio
    async def test_com_device_removed_reinit(self):
        """When the cached COM probe fails, the interface is re-created."""
        from backend.plugins.media_control import executor as exec_mod

        stale_iface = MagicMock()
        stale_iface.GetMasterVolumeLevelScalar.side_effect = Exception("device gone")

        fresh_iface = _mock_volume_interface(scalar=0.3)

        # Simulate cached stale interface
        orig = exec_mod._volume_interface
        orig_is_win = exec_mod._IS_WINDOWS
        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        try:
            exec_mod._IS_WINDOWS = True
            exec_mod._PYCAW_AVAILABLE = True
            exec_mod._volume_interface = stale_iface

            # Mock AudioUtilities.GetSpeakers to return a mock device
            mock_device = MagicMock()
            mock_activate = MagicMock()
            mock_activate.QueryInterface.return_value = fresh_iface
            mock_device.Activate.return_value = mock_activate

            mock_au = MagicMock()
            mock_au.GetSpeakers.return_value = mock_device
            mock_iid = MagicMock(_iid_=MagicMock())

            with patch.object(
                exec_mod, "AudioUtilities", mock_au, create=True,
            ), patch.object(
                exec_mod, "IAudioEndpointVolume", mock_iid, create=True,
            ), patch.object(
                exec_mod, "CLSCTX_ALL", 0, create=True,
            ):
                from backend.plugins.media_control.plugin import MediaControlPlugin

                plugin = MediaControlPlugin()
                ctx = _make_app_context()
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "get_volume", {}, _make_exec_ctx(),
                )

            assert result.success
            assert "30%" in result.content
        finally:
            exec_mod._volume_interface = orig
            exec_mod._IS_WINDOWS = orig_is_win
            exec_mod._PYCAW_AVAILABLE = orig_pycaw

    @pytest.mark.asyncio
    async def test_com_exception_returns_error(self):
        """An OSError from COM → error ToolResult."""
        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            side_effect=OSError("COM RPC unavailable"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("get_volume", {}, _make_exec_ctx())

        assert not result.success
        assert "OSError" in result.error_message

    @pytest.mark.asyncio
    async def test_no_audio_device_found(self):
        """GetSpeakers returns None → RuntimeError."""
        from backend.plugins.media_control import executor as exec_mod

        orig = exec_mod._volume_interface
        orig_is_win = exec_mod._IS_WINDOWS
        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        try:
            exec_mod._IS_WINDOWS = True
            exec_mod._PYCAW_AVAILABLE = True
            exec_mod._volume_interface = None

            mock_au = MagicMock()
            mock_au.GetSpeakers.return_value = None
            mock_iid = MagicMock(_iid_=MagicMock())

            with patch.object(
                exec_mod, "AudioUtilities", mock_au, create=True,
            ), patch.object(
                exec_mod, "IAudioEndpointVolume", mock_iid, create=True,
            ), patch.object(
                exec_mod, "CLSCTX_ALL", 0, create=True,
            ):
                from backend.plugins.media_control.plugin import MediaControlPlugin

                plugin = MediaControlPlugin()
                ctx = _make_app_context()
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "get_volume", {}, _make_exec_ctx(),
                )

            assert not result.success
            assert "No audio" in result.error_message or "device" in result.error_message
        finally:
            exec_mod._volume_interface = orig
            exec_mod._IS_WINDOWS = orig_is_win
            exec_mod._PYCAW_AVAILABLE = orig_pycaw

    @pytest.mark.asyncio
    async def test_unexpected_exception_handled(self):
        """Unexpected exceptions are caught and return a safe error."""
        with patch(
            "backend.plugins.media_control.executor._get_volume_interface",
            side_effect=TypeError("unexpected"),
        ):
            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("mute", {}, _make_exec_ctx())

        assert not result.success
        assert "Unexpected error" in result.error_message

    @pytest.mark.asyncio
    async def test_pycaw_not_available(self):
        """When pycaw is missing, _get_volume_interface raises RuntimeError."""
        from backend.plugins.media_control import executor as exec_mod

        orig = exec_mod._volume_interface
        orig_is_win = exec_mod._IS_WINDOWS
        orig_pycaw = exec_mod._PYCAW_AVAILABLE
        try:
            exec_mod._IS_WINDOWS = True
            exec_mod._PYCAW_AVAILABLE = False
            exec_mod._volume_interface = None

            from backend.plugins.media_control.plugin import MediaControlPlugin

            plugin = MediaControlPlugin()
            ctx = _make_app_context()
            await plugin.initialize(ctx)

            result = await plugin.execute_tool("get_volume", {}, _make_exec_ctx())

            assert not result.success
            assert "pycaw" in result.error_message
        finally:
            exec_mod._volume_interface = orig
            exec_mod._IS_WINDOWS = orig_is_win
            exec_mod._PYCAW_AVAILABLE = orig_pycaw
