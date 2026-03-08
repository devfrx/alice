"""Tests for backend.plugins.weather — WeatherPlugin & WeatherClient."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult
from backend.plugins.weather.client import WeatherClient, _weather_code_text
from backend.plugins.weather.plugin import WeatherPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_app_context(**overrides) -> AppContext:
    """Build a minimal AppContext with default config."""
    config = load_config()
    return AppContext(
        config=config,
        event_bus=EventBus(),
        **overrides,
    )


# -- Fake API responses ----------------------------------------------------

_DUMMY_REQUEST = httpx.Request("GET", "https://test.example.com")


def _ok_response(json_data: dict) -> httpx.Response:
    """Build a 200 httpx.Response with a request attached."""
    return httpx.Response(200, json=json_data, request=_DUMMY_REQUEST)


GEOCODING_RESPONSE = {
    "results": [
        {"latitude": 41.8933, "longitude": 12.4829, "name": "Rome"},
    ],
}

GEOCODING_EMPTY = {"results": []}

CURRENT_WEATHER_RESPONSE = {
    "current": {
        "temperature_2m": 22.5,
        "apparent_temperature": 21.0,
        "relative_humidity_2m": 55,
        "wind_speed_10m": 12.3,
        "weather_code": 1,
        "uv_index": 6.0,
    },
}

FORECAST_RESPONSE_3D = {
    "daily": {
        "time": ["2026-03-08", "2026-03-09", "2026-03-10"],
        "temperature_2m_max": [18.0, 20.0, 17.5],
        "temperature_2m_min": [8.0, 10.0, 7.5],
        "weather_code": [0, 3, 61],
        "precipitation_probability_max": [0, 10, 75],
    },
}


# ===========================================================================
# 1.  Plugin lifecycle
# ===========================================================================


class TestWeatherPluginLifecycle:
    """Verify plugin attributes, init, cleanup and connection status."""

    def test_plugin_class_attributes(self):
        plugin = WeatherPlugin()
        assert plugin.plugin_name == "weather"
        assert plugin.plugin_priority == 35
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_dependencies == []

    @pytest.mark.asyncio
    async def test_initialize_creates_client(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        assert plugin._client is not None
        assert isinstance(plugin._client, WeatherClient)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_get_tools_returns_two(self):
        plugin = WeatherPlugin()
        tools = plugin.get_tools()
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_tool_names_and_risk_levels(self):
        plugin = WeatherPlugin()
        tools = {t.name: t for t in plugin.get_tools()}
        assert "get_weather" in tools
        assert "get_weather_forecast" in tools
        assert tools["get_weather"].risk_level == "safe"
        assert tools["get_weather_forecast"].risk_level == "safe"

    @pytest.mark.asyncio
    async def test_cleanup_closes_client(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        mock_close = AsyncMock()
        plugin._client.close = mock_close  # type: ignore[union-attr]

        await plugin.cleanup()
        mock_close.assert_awaited_once()
        assert plugin._client is None

    @pytest.mark.asyncio
    async def test_connection_status_connected(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_connection_status_disconnected_no_client(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)
        plugin._client = None

        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connection_status_disconnected_on_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(side_effect=Exception("offline"))  # type: ignore[union-attr]
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.DISCONNECTED
        await plugin.cleanup()


# ===========================================================================
# 2.  get_weather tool execution
# ===========================================================================


class TestGetWeatherTool:
    """Test execute_tool('get_weather', ...) with mocked WeatherClient."""

    @pytest.mark.asyncio
    async def test_get_weather_with_explicit_city(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_current = AsyncMock(return_value={  # type: ignore[union-attr]
            "temperature": 22.5,
            "feels_like": 21.0,
            "humidity": 55,
            "wind_speed": 12.3,
            "condition": "Mainly clear",
            "uv_index": 6.0,
        })

        result = await plugin.execute_tool(
            "get_weather", {"city": "Milan"}, _make_exec_ctx(),
        )

        assert result.success is True
        assert result.content["city"] == "Milan"
        assert result.content["temperature"] == 22.5
        plugin._client.get_coordinates.assert_awaited_once_with("Milan", ctx.config.weather.lang)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_get_weather_uses_default_city(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_current = AsyncMock(return_value={  # type: ignore[union-attr]
            "temperature": 20.0,
            "feels_like": 19.0,
            "humidity": 60,
            "wind_speed": 5.0,
            "condition": "Clear sky",
            "uv_index": 3.0,
        })

        result = await plugin.execute_tool(
            "get_weather", {}, _make_exec_ctx(),
        )

        assert result.success is True
        default_city = ctx.config.weather.default_city
        assert result.content["city"] == default_city
        plugin._client.get_coordinates.assert_awaited_once_with(default_city, ctx.config.weather.lang)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_get_weather_city_not_found(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=ValueError("City not found: Atlantis"),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "Atlantis"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "City not found" in result.error_message
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_get_weather_service_unavailable_http_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        resp = httpx.Response(503, request=httpx.Request("GET", "https://example.com"))
        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=httpx.HTTPStatusError("503", request=resp.request, response=resp),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "Rome"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "unavailable" in result.error_message.lower()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_get_weather_service_unavailable_connect_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=httpx.ConnectError("Connection refused"),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "Rome"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "unavailable" in result.error_message.lower()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_get_weather_not_initialised(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)
        plugin._client = None

        result = await plugin.execute_tool(
            "get_weather", {"city": "Rome"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "not initialised" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_unknown_tool_name(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "get_nothing", {}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "Unknown tool" in result.error_message
        await plugin.cleanup()


# ===========================================================================
# 3.  get_weather_forecast tool execution
# ===========================================================================


class TestGetWeatherForecastTool:
    """Test execute_tool('get_weather_forecast', ...) with mocked client."""

    @pytest.fixture
    def forecast_data(self):
        return [
            {"date": "2026-03-08", "temp_max": 18.0, "temp_min": 8.0,
             "condition": "Clear sky", "precipitation_prob": 0},
            {"date": "2026-03-09", "temp_max": 20.0, "temp_min": 10.0,
             "condition": "Overcast", "precipitation_prob": 10},
            {"date": "2026-03-10", "temp_max": 17.5, "temp_min": 7.5,
             "condition": "Slight rain", "precipitation_prob": 75},
        ]

    @pytest.mark.asyncio
    async def test_forecast_with_city_and_days(self, forecast_data):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_forecast = AsyncMock(return_value=forecast_data)  # type: ignore[union-attr]

        result = await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome", "days": 3},
            _make_exec_ctx(),
        )

        assert result.success is True
        assert result.content["city"] == "Rome"
        assert len(result.content["days"]) == 3
        plugin._client.get_forecast.assert_awaited_once_with(41.89, 12.48, 3)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_forecast_default_days(self, forecast_data):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_forecast = AsyncMock(return_value=forecast_data)  # type: ignore[union-attr]

        result = await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome"},
            _make_exec_ctx(),
        )

        assert result.success is True
        # Default is 3 days
        plugin._client.get_forecast.assert_awaited_once_with(41.89, 12.48, 3)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_forecast_days_clamped_by_plugin(self):
        """Plugin clamps days to [1, 16] before passing to client."""
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_forecast = AsyncMock(return_value=[])  # type: ignore[union-attr]

        await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome", "days": 30},
            _make_exec_ctx(),
        )

        # Plugin clamps 30 → 16
        plugin._client.get_forecast.assert_awaited_once_with(41.89, 12.48, 16)
        await plugin.cleanup()


# ===========================================================================
# 4.  WeatherClient — httpx mocked
# ===========================================================================


class TestWeatherClient:
    """Unit tests for WeatherClient with mocked HTTP transport."""

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_get_coordinates_success(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(GEOCODING_RESPONSE)

        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]
        lat, lon = await client.get_coordinates("Rome", "en")

        assert lat == pytest.approx(41.8933)
        assert lon == pytest.approx(12.4829)
        mock_ssrf.assert_called()
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_get_coordinates_city_not_found(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(GEOCODING_EMPTY)

        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="City not found"):
            await client.get_coordinates("Atlantis", "en")

        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_get_coordinates_caching(self, mock_ssrf):
        """Second call for same city should hit cache → only 1 HTTP call."""
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(GEOCODING_RESPONSE)

        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        await client.get_coordinates("Rome", "en")
        await client.get_coordinates("Rome", "en")

        # Only one HTTP call despite two invocations
        assert client._http.get.await_count == 1
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_get_current_weather(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(CURRENT_WEATHER_RESPONSE)

        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]
        result = await client.get_current(41.89, 12.48)

        assert result["temperature"] == 22.5
        assert result["feels_like"] == 21.0
        assert result["humidity"] == 55
        assert result["wind_speed"] == 12.3
        assert result["condition"] == "Mainly clear"
        assert result["uv_index"] == 6.0
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_get_forecast(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(FORECAST_RESPONSE_3D)

        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]
        result = await client.get_forecast(41.89, 12.48, days=3)

        assert len(result) == 3
        assert result[0]["date"] == "2026-03-08"
        assert result[0]["temp_max"] == 18.0
        assert result[0]["temp_min"] == 8.0
        assert result[0]["condition"] == "Clear sky"
        assert result[0]["precipitation_prob"] == 0
        assert result[2]["condition"] == "Slight rain"
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_get_forecast_clamps_days(self, mock_ssrf):
        """days > 16 → clamped to 16; days < 1 → clamped to 1."""
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        # Single-day response
        single_day_resp = {
            "daily": {
                "time": ["2026-03-08"],
                "temperature_2m_max": [18.0],
                "temperature_2m_min": [8.0],
                "weather_code": [0],
                "precipitation_probability_max": [0],
            },
        }
        mock_resp = _ok_response(single_day_resp)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        # days=0 → clamped to 1
        result = await client.get_forecast(41.89, 12.48, days=0)
        call_params = client._http.get.call_args
        assert call_params.kwargs.get("params", {}).get("forecast_days") == 1

        # Reset mock and cache
        client._weather_cache.clear()
        client._http.get = AsyncMock(return_value=_ok_response(single_day_resp))  # type: ignore[method-assign]

        # days=20 → clamped to 16
        await client.get_forecast(41.89, 12.48, days=20)
        call_params = client._http.get.call_args
        assert call_params.kwargs.get("params", {}).get("forecast_days") == 16

        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_close_calls_aclose(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        client._http.aclose = AsyncMock()  # type: ignore[method-assign]

        await client.close()

        client._http.aclose.assert_awaited_once()
        assert client._geo_cache == {}
        assert client._weather_cache == {}

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_ssrf_validation_called_for_geocoding(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(GEOCODING_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        await client.get_coordinates("Rome", "en")

        mock_ssrf.assert_awaited_once_with("https://geocoding-api.open-meteo.com/v1/search")
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_ssrf_validation_called_for_forecast(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(CURRENT_WEATHER_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        await client.get_current(41.89, 12.48)

        mock_ssrf.assert_awaited_once_with("https://api.open-meteo.com/v1/forecast")
        await client.close()

    def test_weather_code_text_known(self):
        assert _weather_code_text(0) == "Clear sky"
        assert _weather_code_text(95) == "Thunderstorm"

    def test_weather_code_text_unknown(self):
        assert "Unknown" in _weather_code_text(999)


# ===========================================================================
# 5.  Caching behaviour
# ===========================================================================


class TestWeatherCaching:
    """Verify in-memory cache hit / expiry semantics."""

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_current_weather_cache_hit(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(CURRENT_WEATHER_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        result1 = await client.get_current(41.89, 12.48)
        result2 = await client.get_current(41.89, 12.48)

        assert result1 == result2
        assert client._http.get.await_count == 1
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_forecast_cache_hit(self, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        mock_resp = _ok_response(FORECAST_RESPONSE_3D)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        result1 = await client.get_forecast(41.89, 12.48, 3)
        result2 = await client.get_forecast(41.89, 12.48, 3)

        assert result1 == result2
        assert client._http.get.await_count == 1
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    @patch("backend.plugins.weather.client.time.monotonic")
    async def test_geo_cache_expires_after_ttl(self, mock_monotonic, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=60)
        mock_resp = _ok_response(GEOCODING_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        # First call at t=100
        mock_monotonic.return_value = 100.0
        await client.get_coordinates("Rome", "en")
        assert client._http.get.await_count == 1

        # Second call at t=110 → still cached (TTL=60)
        mock_monotonic.return_value = 110.0
        await client.get_coordinates("Rome", "en")
        assert client._http.get.await_count == 1

        # Third call at t=161 → cache expired
        mock_monotonic.return_value = 161.0
        await client.get_coordinates("Rome", "en")
        assert client._http.get.await_count == 2

        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    @patch("backend.plugins.weather.client.time.monotonic")
    async def test_weather_cache_expires_after_ttl(self, mock_monotonic, mock_ssrf):
        client = WeatherClient(timeout_s=5, cache_ttl_s=60)
        mock_resp = _ok_response(CURRENT_WEATHER_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        mock_monotonic.return_value = 200.0
        await client.get_current(41.89, 12.48)
        assert client._http.get.await_count == 1

        # Still within TTL
        mock_monotonic.return_value = 250.0
        await client.get_current(41.89, 12.48)
        assert client._http.get.await_count == 1

        # TTL expired
        mock_monotonic.return_value = 261.0
        await client.get_current(41.89, 12.48)
        assert client._http.get.await_count == 2

        await client.close()


# ===========================================================================
# 6.  Edge cases
# ===========================================================================


class TestWeatherEdgeCases:
    """Error handling and corner cases."""

    @pytest.mark.asyncio
    async def test_city_not_found_returns_tool_result_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=ValueError("City not found: Nowhere"),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "Nowhere"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "City not found" in result.error_message
        assert result.execution_time_ms > 0
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_api_offline_http_status_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        resp = httpx.Response(500, request=httpx.Request("GET", "https://example.com"))
        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=httpx.HTTPStatusError("500", request=resp.request, response=resp),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "Rome"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "unavailable" in result.error_message.lower()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_api_offline_timeout(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=httpx.TimeoutException("timed out"),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "Rome"}, _make_exec_ctx(),
        )

        assert result.success is False
        assert "unavailable" in result.error_message.lower()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_connection_status_disconnected_on_api_failure(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=httpx.ConnectError("offline"),
        )

        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.DISCONNECTED
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_execution_time_recorded_on_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=ValueError("City not found: X"),
        )

        result = await plugin.execute_tool(
            "get_weather", {"city": "X"}, _make_exec_ctx(),
        )

        assert result.execution_time_ms >= 0
        await plugin.cleanup()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_ssrf_validation_failure_propagates(self, mock_ssrf):
        mock_ssrf.side_effect = ValueError("SSRF blocked")
        client = WeatherClient(timeout_s=5, cache_ttl_s=600)
        client._http.get = AsyncMock()  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="SSRF blocked"):
            await client.get_coordinates("evil.local", "en")

        # HTTP call should not have been made
        client._http.get.assert_not_awaited()
        await client.close()

    @pytest.mark.asyncio
    async def test_forecast_error_returns_tool_result_error(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(  # type: ignore[union-attr]
            side_effect=httpx.ConnectError("offline"),
        )

        result = await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome", "days": 3},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "unavailable" in result.error_message.lower()
        await plugin.cleanup()


# ===========================================================================
# 7.  New tests — cache bound, days clamping, check_dependencies
# ===========================================================================


class TestCacheBound:
    """Verify FIFO eviction when cache exceeds max entries."""

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_weather_cache_evicts_at_max(self, mock_ssrf):
        """Oldest weather entries are evicted once cache exceeds 100."""
        from backend.plugins.weather.client import _MAX_CACHE_ENTRIES

        client = WeatherClient(timeout_s=5, cache_ttl_s=600)

        # Pre-fill cache to the limit
        for i in range(_MAX_CACHE_ENTRIES):
            client._weather_cache[f"key:{i}"] = (time.monotonic(), {"data": i})

        assert len(client._weather_cache) == _MAX_CACHE_ENTRIES

        # One more insert via actual API call triggers eviction
        mock_resp = _ok_response(CURRENT_WEATHER_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]
        await client.get_current(99.0, 99.0)

        assert len(client._weather_cache) <= _MAX_CACHE_ENTRIES
        # The very first manually inserted key should have been evicted
        assert "key:0" not in client._weather_cache
        await client.close()

    @pytest.mark.asyncio
    @patch("backend.plugins.weather.client.async_validate_url_ssrf", new_callable=AsyncMock)
    async def test_geo_cache_evicts_at_max(self, mock_ssrf):
        """Oldest geocoding entries are evicted once cache exceeds 100."""
        from backend.plugins.weather.client import _MAX_CACHE_ENTRIES

        client = WeatherClient(timeout_s=5, cache_ttl_s=600)

        for i in range(_MAX_CACHE_ENTRIES):
            client._geo_cache[(f"city{i}", "en")] = (time.monotonic(), (0.0, 0.0))

        assert len(client._geo_cache) == _MAX_CACHE_ENTRIES

        mock_resp = _ok_response(GEOCODING_RESPONSE)
        client._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]
        await client.get_coordinates("NewCity", "en")

        assert len(client._geo_cache) <= _MAX_CACHE_ENTRIES
        assert ("city0", "en") not in client._geo_cache
        await client.close()


class TestPluginDaysClamping:
    """Verify the plugin clamps forecast days to [1, 16]."""

    @pytest.mark.asyncio
    async def test_days_clamped_to_16_when_above(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_forecast = AsyncMock(return_value=[])  # type: ignore[union-attr]

        await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome", "days": 30},
            _make_exec_ctx(),
        )

        plugin._client.get_forecast.assert_awaited_once_with(41.89, 12.48, 16)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_days_clamped_to_1_when_below(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_forecast = AsyncMock(return_value=[])  # type: ignore[union-attr]

        await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome", "days": -5},
            _make_exec_ctx(),
        )

        plugin._client.get_forecast.assert_awaited_once_with(41.89, 12.48, 1)
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_valid_days_pass_through(self):
        plugin = WeatherPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)

        plugin._client.get_coordinates = AsyncMock(return_value=(41.89, 12.48))  # type: ignore[union-attr]
        plugin._client.get_forecast = AsyncMock(return_value=[])  # type: ignore[union-attr]

        await plugin.execute_tool(
            "get_weather_forecast",
            {"city": "Rome", "days": 10},
            _make_exec_ctx(),
        )

        plugin._client.get_forecast.assert_awaited_once_with(41.89, 12.48, 10)
        await plugin.cleanup()


class TestCheckDependencies:
    """Verify check_dependencies override."""

    def test_check_dependencies_returns_empty(self):
        plugin = WeatherPlugin()
        assert plugin.check_dependencies() == []