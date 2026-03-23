"""AL\\CE — Tests for VRAM monitor service (Phase 4)."""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from unittest.mock import MagicMock, patch

from backend.core.event_bus import EventBus
from backend.services.vram_monitor import VRAMMonitor, VRAMUsage


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meminfo(total_gb: float = 16, used_gb: float = 8) -> MagicMock:
    """Return a mock pynvml memory-info object (bytes)."""
    info = MagicMock()
    info.total = int(total_gb * 1024**3)
    info.used = int(used_gb * 1024**3)
    info.free = int((total_gb - used_gb) * 1024**3)
    return info


async def _run_single_poll(monitor: VRAMMonitor) -> VRAMUsage | None:
    """Execute exactly one iteration of ``_poll_loop`` deterministically.

    Patches ``asyncio.sleep`` to raise ``CancelledError`` so the loop
    exits immediately after one cycle — no timing dependency.
    """
    async def _cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    with patch("asyncio.sleep", _cancel_sleep):
        with contextlib.suppress(asyncio.CancelledError):
            await monitor._poll_loop()
    return monitor.last_usage


def _setup_pynvml_monitor(
    event_bus: EventBus,
    mock_pynvml: MagicMock,
    *,
    total_gb: float = 16,
    used_gb: float = 8,
) -> VRAMMonitor:
    """Create a ``VRAMMonitor`` with the pynvml backend configured manually.

    Bypasses ``start()`` so there is no background task — callers drive
    polling explicitly via ``_run_single_poll`` or ``get_usage()``.
    """
    handle = MagicMock()
    mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = handle
    mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(
        total_gb, used_gb,
    )
    monitor = VRAMMonitor(event_bus, poll_interval=999)
    monitor._available = True
    monitor._use_pynvml = True
    monitor._pynvml_handle = handle
    return monitor


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestVRAMMonitorLifecycle:
    @patch("backend.services.vram_monitor._HAS_PYNVML", True)
    @patch("backend.services.vram_monitor._pynvml")
    async def test_start_with_pynvml(self, mock_pynvml, event_bus):
        """Start should succeed when pynvml is available."""
        mock_pynvml.nvmlInit.return_value = None
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(16, 4)

        monitor = VRAMMonitor(event_bus, poll_interval=999)
        await monitor.start()

        mock_pynvml.nvmlInit.assert_called_once()
        assert await monitor.health_check() is True
        await monitor.stop()

    @patch("backend.services.vram_monitor._HAS_PYNVML", False)
    @patch("subprocess.run")
    async def test_start_fallback_nvidia_smi(self, mock_run, event_bus):
        """Should fallback to nvidia-smi when pynvml missing."""
        mock_run.return_value = MagicMock(stdout="16384, 8192\n", returncode=0)

        monitor = VRAMMonitor(event_bus, poll_interval=999)
        await monitor.start()

        assert await monitor.health_check() is True
        await monitor.stop()

    @patch("backend.services.vram_monitor._HAS_PYNVML", False)
    @patch("subprocess.run", side_effect=FileNotFoundError)
    async def test_start_no_gpu(self, mock_run, event_bus):
        """Should handle gracefully when no GPU detected."""
        monitor = VRAMMonitor(event_bus)
        await monitor.start()

        assert await monitor.health_check() is False
        await monitor.stop()

    @patch("backend.services.vram_monitor._HAS_PYNVML", True)
    @patch("backend.services.vram_monitor._pynvml")
    async def test_stop_cancels_polling(self, mock_pynvml, event_bus):
        """Stop should cancel the background poll task."""
        mock_pynvml.nvmlInit.return_value = None
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(16, 4)

        monitor = VRAMMonitor(event_bus, poll_interval=999)
        await monitor.start()
        assert monitor._poll_task is not None
        await monitor.stop()
        assert monitor._poll_task is None or monitor._poll_task.cancelled()

    @patch("backend.services.vram_monitor._HAS_PYNVML", True)
    @patch("backend.services.vram_monitor._pynvml")
    async def test_health_check_true(self, mock_pynvml, event_bus):
        """health_check True when GPU monitoring available."""
        mock_pynvml.nvmlInit.return_value = None
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(16, 4)

        monitor = VRAMMonitor(event_bus, poll_interval=999)
        await monitor.start()
        assert await monitor.health_check() is True
        await monitor.stop()

    async def test_health_check_false_no_gpu(self, event_bus):
        """health_check False when monitor not started / no GPU."""
        monitor = VRAMMonitor(event_bus)
        assert await monitor.health_check() is False


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------


class TestVRAMBudget:
    async def test_register_component(self, event_bus):
        """register_component should track VRAM budget."""
        monitor = VRAMMonitor(event_bus)
        monitor.register_component("llm", 6000)
        monitor.register_component("stt", 1500)

        # _available=False → zeroed usage, but per_component is populated
        usage = await monitor.get_usage()
        assert usage.per_component["llm"] == 6000
        assert usage.per_component["stt"] == 1500

    async def test_unregister_component(self, event_bus):
        """unregister_component should remove from budget."""
        monitor = VRAMMonitor(event_bus)
        monitor.register_component("tts", 2000)
        monitor.unregister_component("tts")

        usage = await monitor.get_usage()
        assert "tts" not in usage.per_component

    @patch("backend.services.vram_monitor._HAS_PYNVML", True)
    @patch("backend.services.vram_monitor._pynvml")
    async def test_get_usage_with_gpu(self, mock_pynvml, event_bus):
        """get_usage should return VRAMUsage with GPU data and budget."""
        mock_pynvml.nvmlInit.return_value = None
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(16, 8)

        monitor = VRAMMonitor(event_bus, poll_interval=999)
        await monitor.start()
        monitor.register_component("llm", 6000)

        usage = await monitor.get_usage()

        assert isinstance(usage, VRAMUsage)
        assert usage.total_mb == 16384
        assert usage.used_mb == 8192
        assert usage.free_mb == 8192
        assert 49.0 <= usage.utilization_percent <= 51.0
        assert usage.per_component["llm"] == 6000
        await monitor.stop()


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class TestVRAMAlerts:
    @patch("backend.services.vram_monitor._pynvml")
    async def test_warning_event_emitted(self, mock_pynvml, event_bus):
        """Should emit vram.warning when warning threshold is crossed."""
        received: list[dict] = []

        async def _handler(**kwargs):
            received.append(kwargs)

        event_bus.subscribe("vram.warning", _handler)

        # 14 GB used → 14336 MB ≥ 14000 MB warning threshold
        monitor = _setup_pynvml_monitor(
            event_bus, mock_pynvml, total_gb=16, used_gb=14,
        )
        await _run_single_poll(monitor)

        assert len(received) == 1

    @patch("backend.services.vram_monitor._pynvml")
    async def test_critical_event_emitted(self, mock_pynvml, event_bus):
        """Should emit vram.critical when critical threshold is crossed."""
        received: list[dict] = []

        async def _handler(**kwargs):
            received.append(kwargs)

        event_bus.subscribe("vram.critical", _handler)

        # 15 GB used → 15360 MB ≥ 15000 MB critical threshold
        monitor = _setup_pynvml_monitor(
            event_bus, mock_pynvml, total_gb=16, used_gb=15,
        )
        await _run_single_poll(monitor)

        assert len(received) == 1

    @patch("backend.services.vram_monitor._pynvml")
    async def test_no_event_under_threshold(self, mock_pynvml, event_bus):
        """No event when VRAM usage is under warning threshold."""
        received: list[dict] = []

        async def _handler(**kwargs):
            received.append(kwargs)

        event_bus.subscribe("vram.warning", _handler)
        event_bus.subscribe("vram.critical", _handler)

        # 4 GB used → well under 14 GB warning threshold
        monitor = _setup_pynvml_monitor(
            event_bus, mock_pynvml, total_gb=16, used_gb=4,
        )
        await _run_single_poll(monitor)

        assert len(received) == 0

    @patch("backend.services.vram_monitor._pynvml")
    async def test_warning_dedup_emits_once(self, mock_pynvml, event_bus):
        """Warning event should fire only once across multiple polls."""
        received: list[dict] = []

        async def _handler(**kwargs):
            received.append(kwargs)

        event_bus.subscribe("vram.warning", _handler)

        monitor = _setup_pynvml_monitor(
            event_bus, mock_pynvml, total_gb=16, used_gb=14,
        )
        # Three consecutive polls with high usage
        await _run_single_poll(monitor)
        await _run_single_poll(monitor)
        await _run_single_poll(monitor)

        assert len(received) == 1

    @patch("backend.services.vram_monitor._pynvml")
    async def test_warning_dedup_resets_after_low_usage(
        self, mock_pynvml, event_bus,
    ):
        """Warning flag resets when usage drops, allowing re-emission."""
        received: list[dict] = []

        async def _handler(**kwargs):
            received.append(kwargs)

        event_bus.subscribe("vram.warning", _handler)

        monitor = _setup_pynvml_monitor(
            event_bus, mock_pynvml, total_gb=16, used_gb=14,
        )

        # First high-usage poll → warning fires
        await _run_single_poll(monitor)
        assert len(received) == 1

        # Low usage → flags reset, no new event
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(16, 4)
        await _run_single_poll(monitor)
        assert len(received) == 1

        # High usage again → warning fires again
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = _make_meminfo(16, 14)
        await _run_single_poll(monitor)
        assert len(received) == 2

    @patch("backend.services.vram_monitor._pynvml")
    async def test_critical_dedup_emits_once(self, mock_pynvml, event_bus):
        """Critical event should fire only once across multiple polls."""
        received: list[dict] = []

        async def _handler(**kwargs):
            received.append(kwargs)

        event_bus.subscribe("vram.critical", _handler)

        monitor = _setup_pynvml_monitor(
            event_bus, mock_pynvml, total_gb=16, used_gb=15,
        )
        await _run_single_poll(monitor)
        await _run_single_poll(monitor)

        assert len(received) == 1


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @patch("backend.services.vram_monitor._HAS_PYNVML", False)
    @patch("subprocess.run", side_effect=FileNotFoundError)
    async def test_no_gpu_returns_empty_usage(self, mock_run, event_bus):
        """When no GPU, get_usage should return zeros."""
        monitor = VRAMMonitor(event_bus)
        await monitor.start()

        usage = await monitor.get_usage()
        assert usage.total_mb == 0
        assert usage.used_mb == 0
        assert usage.free_mb == 0
        assert usage.utilization_percent == 0.0
        assert usage.per_component == {}
        await monitor.stop()

    async def test_get_usage_not_available(self, event_bus):
        """get_usage returns zeroed VRAMUsage when _available is False."""
        monitor = VRAMMonitor(event_bus)

        usage = await monitor.get_usage()
        assert usage.total_mb == 0
        assert usage.used_mb == 0
        assert usage.free_mb == 0
        assert usage.utilization_percent == 0.0

    @patch("backend.services.vram_monitor._HAS_PYNVML", False)
    @patch("subprocess.run")
    async def test_nvidia_smi_fallback_get_usage(self, mock_run, event_bus):
        """get_usage works correctly via nvidia-smi fallback."""
        mock_run.return_value = MagicMock(stdout="16384, 12288\n", returncode=0)

        monitor = VRAMMonitor(event_bus, poll_interval=999)
        await monitor.start()

        usage = await monitor.get_usage()
        assert usage.total_mb == 16384
        assert usage.used_mb == 12288
        assert usage.free_mb == 4096
        await monitor.stop()
