"""Tests for backend.plugins.cad_generator.plugin — CadGeneratorPlugin."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import (
    Trellis2ServiceConfig,
    TrellisServiceConfig,
    load_config,
)
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult
from backend.plugins.cad_generator.client import GenerationResult
from backend.plugins.cad_generator.client_v2 import Trellis2GenerationResult
from backend.plugins.cad_generator.plugin import CadGeneratorPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx(execution_id: str = "abcd1234-0000-0000-0000-000000000000") -> ExecutionContext:
    return ExecutionContext(
        session_id="test-session",
        conversation_id="test-conv",
        execution_id=execution_id,
    )


def _make_trellis_config(tmp_path: Path, **overrides) -> TrellisServiceConfig:
    defaults = {
        "enabled": True,
        "service_url": "http://localhost:8090",
        "request_timeout_s": 10,
        "max_model_size_mb": 100,
        "model_output_dir": str(tmp_path / "3d_models"),
        "auto_vram_swap": True,
        "trellis_model": "TRELLIS-text-large",
        "seed": 42,
    }
    defaults.update(overrides)
    return TrellisServiceConfig(**defaults)


def _make_trellis2_config(tmp_path: Path, **overrides) -> Trellis2ServiceConfig:
    """Build a Trellis2ServiceConfig pointing at *tmp_path* output dir."""
    defaults = {
        "enabled": True,
        "service_url": "http://localhost:8091",
        "request_timeout_s": 10,
        "max_model_size_mb": 100,
        "model_output_dir": str(tmp_path / "3d_models_v2"),
        "auto_vram_swap": True,
        "trellis2_model": "microsoft/TRELLIS.2-4B",
        "pipeline_type": "512",
        "decimation_target": 100_000,
        "texture_size": 1024,
        "seed": 42,
    }
    defaults.update(overrides)
    return Trellis2ServiceConfig(**defaults)


def _make_app_context(
    tmp_path: Path,
    *,
    trellis2_overrides: dict | None = None,
    **config_overrides,
) -> AppContext:
    """Build a minimal AppContext with mocked services."""
    config = load_config()
    trellis_cfg = _make_trellis_config(tmp_path, **config_overrides)
    # Override trellis config on the loaded config
    object.__setattr__(config, "trellis", trellis_cfg)
    # TRELLIS.2 config: disabled by default, opt-in via trellis2_overrides
    if trellis2_overrides is not None:
        trellis2_cfg = _make_trellis2_config(tmp_path, **trellis2_overrides)
        object.__setattr__(config, "trellis2", trellis2_cfg)
    object.__setattr__(config, "project_root", str(tmp_path))

    lmstudio = AsyncMock()
    lmstudio.list_models = AsyncMock(return_value={
        "models": [{
            "key": "test-model",
            "type": "llm",
            "loaded_instances": ["inst-001"],
        }],
    })
    lmstudio.unload_model = AsyncMock(return_value={})
    lmstudio.load_model = AsyncMock(return_value={})

    return AppContext(
        config=config,
        event_bus=EventBus(),
        lmstudio_manager=lmstudio,
    )


def _mock_client() -> AsyncMock:
    """Create a mock TrellisClient with default successful responses."""
    mock = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.get_status = AsyncMock(return_value={
        "status": "ok",
        "model_name": "TRELLIS-text-large",
        "model_loaded": True,
    })
    mock.request_model = AsyncMock(return_value=True)
    mock.generate_from_text = AsyncMock(return_value=GenerationResult(
        model_name="test_cube",
        format="glb",
        size_bytes=2048,
        file_path="/outputs/test_cube.glb",
    ))
    mock.download_model = AsyncMock(return_value=b"glTF" + b"\x00" * 100)
    mock.unload_model = AsyncMock()
    mock.close = AsyncMock()
    return mock


def _mock_client_v2() -> AsyncMock:
    """Create a mock Trellis2Client with default successful responses."""
    mock = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.get_status = AsyncMock(return_value={
        "status": "ok",
        "model_name": "microsoft/TRELLIS.2-4B",
        "model_loaded": True,
    })
    mock.request_model = AsyncMock(return_value=True)
    mock.generate_from_image = AsyncMock(return_value=Trellis2GenerationResult(
        base=GenerationResult(
            model_name="from_image_test",
            format="glb",
            size_bytes=4096,
            file_path="/outputs/from_image_test.glb",
        ),
        pipeline_type="512",
        seed=42,
    ))
    mock.download_model = AsyncMock(return_value=b"glTF" + b"\x00" * 200)
    mock.unload_model = AsyncMock()
    mock.close = AsyncMock()
    return mock


# ===========================================================================
# 1. Plugin lifecycle
# ===========================================================================


class TestPluginLifecycle:
    """CadGeneratorPlugin init, cleanup, connection status."""

    def test_plugin_class_attributes(self) -> None:
        plugin = CadGeneratorPlugin()
        assert plugin.plugin_name == "cad_generator"
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_priority == 20

    @pytest.mark.asyncio
    async def test_initialize_reachable(self, tmp_path: Path) -> None:
        """When TRELLIS is reachable, plugin initializes successfully."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        assert plugin.is_initialized
        mock_instance.health_check.assert_awaited_once()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_initialize_unreachable_no_crash(self, tmp_path: Path) -> None:
        """When TRELLIS is unreachable, plugin loads without crashing."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            mock_instance.health_check = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        assert plugin.is_initialized
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_closes_client(self, tmp_path: Path) -> None:
        """cleanup() must call client.close()."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        await plugin.cleanup()
        mock_instance.close.assert_awaited_once()


# ===========================================================================
# 2. Tool definition
# ===========================================================================


class TestToolDefinition:
    """get_tools() returns correct ToolDefinition for cad_generate."""

    def test_cad_generate_tool_definition(self) -> None:
        plugin = CadGeneratorPlugin()
        tools = plugin.get_tools()

        assert len(tools) >= 1
        cad_tool = next((t for t in tools if t.name == "cad_generate"), None)
        assert cad_tool is not None
        assert cad_tool.timeout_ms == 1_230_000  # (1200 + 30) * 1000
        assert cad_tool.risk_level == "safe"
        assert "description" in cad_tool.parameters.get("properties", {})


# ===========================================================================
# 3. Tool execution — cad_generate
# ===========================================================================


class TestCadGenerate:
    """execute_tool('cad_generate', ...) with mocked TrellisClient."""

    @pytest.mark.asyncio
    async def test_cad_generate_success(self, tmp_path: Path) -> None:
        """Successful generation → ToolResult with CAD model JSON payload."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=False)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "a red cube", "model_name": "test_cube"},
            _make_exec_ctx(),
        )

        assert result.success is True
        assert result.content_type == "application/json"
        payload = result.content
        assert payload["model_name"] == "test_cube"
        assert payload["export_url"] == "/api/cad/models/test_cube"
        assert payload["format"] == "glb"
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cad_generate_microservice_offline(self, tmp_path: Path) -> None:
        """health_check False during execution → error ToolResult."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=False)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        # Now make health check fail
        mock_instance.health_check = AsyncMock(return_value=False)

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "a blue sphere"},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "not reachable" in (result.error_message or result.content or "")
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cad_generate_generation_error(self, tmp_path: Path) -> None:
        """Generation raises exception → error ToolResult."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=False)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            mock_instance.generate_from_text = AsyncMock(
                side_effect=Exception("GPU OOM"),
            )
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "something complex"},
            _make_exec_ctx(),
        )

        assert result.success is False
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cad_generate_auto_name(self, tmp_path: Path) -> None:
        """No model_name → name generated from description."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=False)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_gen = GenerationResult(
                model_name="a_simple_box",
                format="glb",
                size_bytes=512,
                file_path="/outputs/a_simple_box.glb",
            )
            mock_instance = _mock_client()
            mock_instance.generate_from_text = AsyncMock(return_value=mock_gen)
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "a simple box"},
            _make_exec_ctx(execution_id="abcd1234-0000-0000-0000-000000000000"),
        )

        assert result.success is True
        payload = result.content
        # Auto-name is derived from the description, not execution_id
        assert payload["model_name"] == "a_simple_box"
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cad_generate_sanitizes_name(self, tmp_path: Path) -> None:
        """model_name with invalid chars → sanitized (slashes/dashes to underscores)."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=False)

        sanitized_gen = GenerationResult(
            model_name="test_model_v2",
            format="glb",
            size_bytes=512,
            file_path="/outputs/test_model_v2.glb",
        )
        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            mock_instance.generate_from_text = AsyncMock(return_value=sanitized_gen)
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "versioned model", "model_name": "test-model/v2"},
            _make_exec_ctx(),
        )

        assert result.success is True
        payload = result.content
        # Slashes and dashes replaced with underscores
        assert "/" not in payload["model_name"]
        assert "-" not in payload["model_name"]
        await plugin.cleanup()


# ===========================================================================
# 4. VRAM swap orchestration
# ===========================================================================


class TestVRAMSwap:
    """VRAM unload/reload LLM around TRELLIS generation."""

    @pytest.mark.asyncio
    async def test_vram_swap_unload_reload(self, tmp_path: Path) -> None:
        """auto_vram_swap=True → LLM unloaded before, reloaded after generation."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=True)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        # Make list_models return loaded model for reload check
        lmstudio = ctx.lmstudio_manager
        lmstudio.list_models = AsyncMock(return_value={
            "models": [{
                "key": "test-model",
                "type": "llm",
                "loaded_instances": ["inst-001"],
            }],
        })

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "a vase"},
            _make_exec_ctx(),
        )

        assert result.success is True
        # Verify LLM was unloaded and reloaded
        lmstudio.unload_model.assert_awaited()
        lmstudio.load_model.assert_awaited()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_vram_swap_disabled(self, tmp_path: Path) -> None:
        """auto_vram_swap=False → no unload/load calls on LM Studio."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=False)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        await plugin.execute_tool(
            "cad_generate",
            {"description": "a simple cube"},
            _make_exec_ctx(),
        )

        lmstudio = ctx.lmstudio_manager
        lmstudio.unload_model.assert_not_awaited()
        lmstudio.load_model.assert_not_awaited()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_vram_swap_reload_after_trellis_failure(self, tmp_path: Path) -> None:
        """TRELLIS generation fails → LLM is still reloaded (safety guarantee)."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(tmp_path, auto_vram_swap=True)

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            mock_instance = _mock_client()
            mock_instance.generate_from_text = AsyncMock(
                side_effect=Exception("TRELLIS crashed"),
            )
            MockClient.return_value = mock_instance
            await plugin.initialize(ctx)

        lmstudio = ctx.lmstudio_manager
        lmstudio.list_models = AsyncMock(return_value={
            "models": [{
                "key": "test-model",
                "type": "llm",
                "loaded_instances": ["inst-001"],
            }],
        })

        result = await plugin.execute_tool(
            "cad_generate",
            {"description": "crash test"},
            _make_exec_ctx(),
        )

        assert result.success is False
        # LLM must be reloaded even after TRELLIS failure
        lmstudio.load_model.assert_awaited()
        await plugin.cleanup()


# ===========================================================================
# 5. TRELLIS.2 image-to-3D tool
# ===========================================================================


def _stage_uploaded_image(
    name: str = "test.png",
    payload: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
) -> tuple[Path, str]:
    """Place a fake image under PROJECT_ROOT/data/uploads/<conv>/.

    Returns ``(absolute_path, relative_path)``.  We use the real
    ``PROJECT_ROOT`` because the plugin resolves uploads against that
    constant; the file lives under a uniquely-named conversation dir
    so concurrent test runs do not clash.
    """
    from backend.core.config import PROJECT_ROOT

    conv_dir = PROJECT_ROOT / "data" / "uploads" / "_pytest_cad_v2"
    conv_dir.mkdir(parents=True, exist_ok=True)
    abs_path = conv_dir / name
    abs_path.write_bytes(payload)
    rel_path = abs_path.relative_to(PROJECT_ROOT).as_posix()
    return abs_path, rel_path


class TestCadGenerateFromImage:
    """execute_tool('cad_generate_from_image', ...) — TRELLIS.2 flow."""

    @pytest.mark.asyncio
    async def test_tool_hidden_when_trellis2_disabled(self, tmp_path: Path) -> None:
        """trellis2.enabled=False → cad_generate_from_image not exposed."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(
            tmp_path,
            trellis2_overrides={"enabled": False},
        )

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient:
            MockClient.return_value = _mock_client()
            await plugin.initialize(ctx)

        names = [t.name for t in plugin.get_tools()]
        assert "cad_generate" in names
        assert "cad_generate_from_image" not in names
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_tool_exposed_when_trellis2_enabled(self, tmp_path: Path) -> None:
        """trellis2.enabled=True → cad_generate_from_image present with image_path."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(
            tmp_path, trellis2_overrides={"auto_vram_swap": False},
        )

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
             patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
            MockClient.return_value = _mock_client()
            MockClient2.return_value = _mock_client_v2()
            await plugin.initialize(ctx)

        tools = {t.name: t for t in plugin.get_tools()}
        assert "cad_generate_from_image" in tools
        params = tools["cad_generate_from_image"].parameters
        assert "image_path" in params.get("properties", {})
        assert "image_path" in params.get("required", [])
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_generate_from_image_success(self, tmp_path: Path) -> None:
        """End-to-end: valid upload → GLB downloaded and saved on disk."""
        abs_path, rel_path = _stage_uploaded_image("ok.png")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": False},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "cad_generate_from_image",
                    {"image_path": rel_path, "model_name": "from_image_test",
                     "pipeline_type": "512"},
                    _make_exec_ctx(),
                )

            assert result.success is True
            payload = result.content
            assert payload["model_name"] == "from_image_test"
            assert payload["pipeline_type"] == "512"
            assert payload["source_image"] == rel_path
            assert payload["export_url"] == "/api/cad/models/from_image_test"
            # File written under cfg2.model_output_dir (tmp_path/3d_models_v2)
            output_file = Path(payload["file_path"])
            assert output_file.exists()
            mock2.generate_from_image.assert_awaited_once()
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_generate_from_image_recovers_local_glb_after_error(
        self, tmp_path: Path,
    ) -> None:
        """If TRELLIS.2 wrote the GLB before failing HTTP, recover it."""
        abs_path, rel_path = _stage_uploaded_image("recover.png")
        output_dir = tmp_path / "3d_models_v2"
        output_dir.mkdir(parents=True, exist_ok=True)
        recovered_file = output_dir / "recovered_model.glb"
        recovered_file.write_bytes(b"glTF" + b"recovered")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": False},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                mock2.generate_from_image = AsyncMock(
                    side_effect=Exception("endpoint cancelled"),
                )
                mock2.download_model = AsyncMock(
                    side_effect=Exception("service already stopped"),
                )
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "cad_generate_from_image",
                    {"image_path": rel_path, "model_name": "recovered_model"},
                    _make_exec_ctx(),
                )

            assert result.success is True
            payload = result.content
            assert payload["model_name"] == "recovered_model"
            assert payload["size_bytes"] == recovered_file.stat().st_size
            assert Path(payload["file_path"]) == recovered_file
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """image_path outside data/uploads/ → error, no client call."""
        plugin = CadGeneratorPlugin()
        ctx = _make_app_context(
            tmp_path, trellis2_overrides={"auto_vram_swap": False},
        )

        with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
             patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
            MockClient.return_value = _mock_client()
            mock2 = _mock_client_v2()
            MockClient2.return_value = mock2
            await plugin.initialize(ctx)

            result = await plugin.execute_tool(
                "cad_generate_from_image",
                {"image_path": "../../etc/passwd"},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "data/uploads" in (result.error_message or result.content or "")
        mock2.generate_from_image.assert_not_awaited()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_unsupported_extension_rejected(self, tmp_path: Path) -> None:
        """image_path with non-image extension → error, no generation."""
        abs_path, rel_path = _stage_uploaded_image("evil.exe", payload=b"MZ\x90\x00")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": False},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "cad_generate_from_image",
                    {"image_path": rel_path},
                    _make_exec_ctx(),
                )

            assert result.success is False
            assert "extension" in (result.error_message or result.content or "").lower()
            mock2.generate_from_image.assert_not_awaited()
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_invalid_pipeline_type_rejected(self, tmp_path: Path) -> None:
        """pipeline_type not in allowed set → error before any service call."""
        abs_path, rel_path = _stage_uploaded_image("img.png")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": False},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "cad_generate_from_image",
                    {"image_path": rel_path, "pipeline_type": "9999"},
                    _make_exec_ctx(),
                )

            assert result.success is False
            assert "pipeline_type" in (result.error_message or result.content or "")
            mock2.generate_from_image.assert_not_awaited()
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_microservice_offline(self, tmp_path: Path) -> None:
        """Trellis2 health_check False → error, no generation attempted."""
        abs_path, rel_path = _stage_uploaded_image("img.png")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": False},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                mock2.health_check = AsyncMock(return_value=False)
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "cad_generate_from_image",
                    {"image_path": rel_path},
                    _make_exec_ctx(),
                )

            assert result.success is False
            assert "not reachable" in (result.error_message or result.content or "")
            mock2.generate_from_image.assert_not_awaited()
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_vram_swap_reload_after_failure(self, tmp_path: Path) -> None:
        """generate_from_image raises → LLM still reloaded (safety guarantee)."""
        abs_path, rel_path = _stage_uploaded_image("img.png")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": True},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2:
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                mock2.generate_from_image = AsyncMock(
                    side_effect=Exception("CUDA OOM"),
                )
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                result = await plugin.execute_tool(
                    "cad_generate_from_image",
                    {"image_path": rel_path},
                    _make_exec_ctx(),
                )

            assert result.success is False
            lmstudio = ctx.lmstudio_manager
            lmstudio.unload_model.assert_awaited()
            lmstudio.load_model.assert_awaited()
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_vram_swap_reload_after_cancellation(self, tmp_path: Path) -> None:
        """Cancelled image generation must still reload LM Studio models."""
        abs_path, rel_path = _stage_uploaded_image("cancelled.png")
        try:
            plugin = CadGeneratorPlugin()
            ctx = _make_app_context(
                tmp_path, trellis2_overrides={"auto_vram_swap": True},
            )

            with patch("backend.plugins.cad_generator.plugin.TrellisClient") as MockClient, \
                 patch("backend.plugins.cad_generator.plugin.Trellis2Client") as MockClient2, \
                 patch("backend.plugins.cad_generator.plugin.asyncio.sleep", new=AsyncMock()):
                MockClient.return_value = _mock_client()
                mock2 = _mock_client_v2()
                mock2.generate_from_image = AsyncMock(
                    side_effect=asyncio.CancelledError(),
                )
                MockClient2.return_value = mock2
                await plugin.initialize(ctx)

                with pytest.raises(asyncio.CancelledError):
                    await plugin.execute_tool(
                        "cad_generate_from_image",
                        {"image_path": rel_path},
                        _make_exec_ctx(),
                    )

            lmstudio = ctx.lmstudio_manager
            lmstudio.unload_model.assert_awaited()
            lmstudio.load_model.assert_awaited()
            await plugin.cleanup()
        finally:
            abs_path.unlink(missing_ok=True)

