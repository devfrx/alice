"""O.M.N.I.A. — Weather plugin.

Exposes ``get_weather`` and ``get_weather_forecast`` tools powered by the
Open-Meteo free API (no API key required).  All HTTP requests go through
the :class:`WeatherClient` which enforces SSRF validation and in-memory
caching.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

import httpx
from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.weather.client import WeatherClient

if TYPE_CHECKING:
    from backend.core.context import AppContext

_MAX_FORECAST_DAYS = 16


class WeatherPlugin(BasePlugin):
    """Current weather and forecasts via open-meteo.com (free, no API key)."""

    plugin_name: str = "weather"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Current weather and forecasts via open-meteo.com (free, no API key)."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 35

    def __init__(self) -> None:
        super().__init__()
        self._client: WeatherClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Create the weather HTTP client.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        cfg = ctx.config.weather
        self._client = WeatherClient(
            timeout_s=cfg.request_timeout_s,
            cache_ttl_s=cfg.cache_ttl_s,
            units=cfg.units,
        )
        logger.info(
            "Weather plugin ready (default_city={}, lang={})",
            cfg.default_city,
            cfg.lang,
        )

    async def cleanup(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        await super().cleanup()

    def check_dependencies(self) -> list[str]:
        """Return missing optional dependencies (none — httpx is required)."""
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Check connectivity by attempting a geocoding request.

        Returns:
            ``CONNECTED`` if the API responds, ``DISCONNECTED`` otherwise.
        """
        if self._client is None:
            return ConnectionStatus.DISCONNECTED
        try:
            cfg = self.ctx.config.weather
            await self._client.get_coordinates(cfg.default_city, cfg.lang)
            return ConnectionStatus.CONNECTED
        except Exception:
            logger.debug("Weather health-check failed")
            return ConnectionStatus.DISCONNECTED

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for weather queries.

        Returns:
            A list of two ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="get_weather",
                description=(
                    "Get current weather for a city. Returns temperature, "
                    "feels-like, humidity, wind speed, condition and UV index."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": (
                                "City name. Defaults to the configured "
                                "default city if omitted."
                            ),
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=10_000,
            ),
            ToolDefinition(
                name="get_weather_forecast",
                description=(
                    "Get a multi-day weather forecast for a city. Returns "
                    "daily high/low temperatures, condition and precipitation "
                    "probability."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": (
                                "City name. Defaults to the configured "
                                "default city if omitted."
                            ),
                        },
                        "days": {
                            "type": "integer",
                            "description": "Forecast days (1–16). Defaults to 3.",
                            "default": 3,
                            "minimum": 1,
                            "maximum": 16,
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=10_000,
            ),
        ]

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested weather tool.

        Args:
            tool_name: ``"get_weather"`` or ``"get_weather_forecast"``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the JSON payload or an error.
        """
        if self._client is None:
            return ToolResult.error("Weather plugin not initialised")

        cfg = self.ctx.config.weather
        city = args.get("city") or cfg.default_city
        start = time.perf_counter()

        try:
            if tool_name == "get_weather":
                return await self._execute_get_weather(city, cfg.lang, start)
            if tool_name == "get_weather_forecast":
                days = int(args.get("days", 3))
                return await self._execute_get_forecast(
                    city, cfg.lang, days, start,
                )
            return ToolResult.error(f"Unknown tool: {tool_name}")

        except ValueError as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ToolResult.error(str(exc), execution_time_ms=elapsed)

        except httpx.HTTPStatusError as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("Weather API HTTP error: {}", exc)
            return ToolResult.error(
                "Weather service unavailable",
                execution_time_ms=elapsed,
            )

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("Weather API connection error: {}", exc)
            return ToolResult.error(
                "Weather service unavailable",
                execution_time_ms=elapsed,
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error("Unexpected weather tool error: {}", exc)
            return ToolResult.error(
                f"Weather tool error: {exc}",
                execution_time_ms=elapsed,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _execute_get_weather(
        self, city: str, lang: str, start: float,
    ) -> ToolResult:
        """Fetch current weather and return as ToolResult."""
        lat, lon = await self._client.get_coordinates(city, lang)  # type: ignore[union-attr]
        weather = await self._client.get_current(lat, lon)  # type: ignore[union-attr]
        elapsed = (time.perf_counter() - start) * 1000

        return ToolResult.ok(
            content={
                "city": city,
                "temperature": weather["temperature"],
                "feels_like": weather["feels_like"],
                "humidity": weather["humidity"],
                "wind_speed": weather["wind_speed"],
                "condition": weather["condition"],
                "uv_index": weather["uv_index"],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            content_type="application/json",
            execution_time_ms=elapsed,
        )

    async def _execute_get_forecast(
        self, city: str, lang: str, days: int, start: float,
    ) -> ToolResult:
        """Fetch daily forecast and return as ToolResult."""
        days = max(1, min(days, _MAX_FORECAST_DAYS))
        lat, lon = await self._client.get_coordinates(city, lang)  # type: ignore[union-attr]
        forecast = await self._client.get_forecast(lat, lon, days)  # type: ignore[union-attr]
        elapsed = (time.perf_counter() - start) * 1000

        return ToolResult.ok(
            content={"city": city, "days": forecast},
            content_type="application/json",
            execution_time_ms=elapsed,
        )
