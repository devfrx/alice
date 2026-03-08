"""O.M.N.I.A. — Weather HTTP client (open-meteo.com).

Async client for the Open-Meteo free weather API.  Provides geocoding,
current-weather, and daily-forecast endpoints with in-memory caching
and SSRF validation on every outbound request.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

from backend.core.http_security import (
    async_validate_url_ssrf,
    create_ssrf_safe_event_hooks,
)

# ---------------------------------------------------------------------------
# WMO Weather Code → human-readable description
# ---------------------------------------------------------------------------

WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

# ---------------------------------------------------------------------------
# API base URLs (hardcoded — no user input)
# ---------------------------------------------------------------------------

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_MAX_CACHE_ENTRIES = 100

_UNIT_PARAMS: dict[str, dict[str, str]] = {
    "metric": {
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    },
    "imperial": {
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
    },
}


def _weather_code_text(code: int) -> str:
    """Convert a WMO weather code to a human-readable string."""
    return WMO_WEATHER_CODES.get(code, f"Unknown ({code})")


# ---------------------------------------------------------------------------
# WeatherClient
# ---------------------------------------------------------------------------


class WeatherClient:
    """Async HTTP client for Open-Meteo weather data.

    Manages a persistent ``httpx.AsyncClient``, caches geocoding results
    and weather responses in memory, and validates every URL against
    SSRF rules before making a request.

    Args:
        timeout_s: HTTP request timeout in seconds.
        cache_ttl_s: Cache time-to-live in seconds.
    """

    def __init__(
        self,
        timeout_s: float = 8.0,
        cache_ttl_s: int = 600,
        units: str = "metric",
    ) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            follow_redirects=False,
            event_hooks=create_ssrf_safe_event_hooks(),
        )
        self._cache_ttl_s = cache_ttl_s
        self._units = units
        # Cache: key → (timestamp, data)
        self._geo_cache: dict[tuple[str, str], tuple[float, tuple[float, float]]] = {}
        self._weather_cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cached(self, cache_entry: tuple[float, Any] | None) -> bool:
        """Return True if *cache_entry* exists and has not expired."""
        if cache_entry is None:
            return False
        ts, _ = cache_entry
        return (time.monotonic() - ts) < self._cache_ttl_s

    def _enforce_cache_limit(self, cache: dict) -> None:
        """Evict oldest entries (FIFO) when *cache* exceeds the max size."""
        while len(cache) > _MAX_CACHE_ENTRIES:
            oldest_key = next(iter(cache))
            del cache[oldest_key]

    async def _fetch_json(self, url: str, params: dict[str, Any]) -> dict:
        """Validate URL, make GET request, return parsed JSON.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            ValueError: If SSRF validation fails.
        """
        # SSRF validation — hardcoded hosts but validate defensively
        await async_validate_url_ssrf(url)

        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------

    async def get_coordinates(
        self, city: str, lang: str = "en",
    ) -> tuple[float, float]:
        """Resolve a city name to (latitude, longitude) via Open-Meteo geocoding.

        Results are cached by ``(city_lower, lang)`` until the TTL expires.

        Args:
            city: City name to geocode.
            lang: Language for results.

        Returns:
            A ``(latitude, longitude)`` tuple.

        Raises:
            ValueError: If the city cannot be found.
        """
        cache_key = (city.lower(), lang)
        entry = self._geo_cache.get(cache_key)
        if self._is_cached(entry):
            return entry[1]  # type: ignore[index]

        data = await self._fetch_json(
            _GEOCODING_URL,
            {"name": city, "count": 1, "language": lang},
        )

        results = data.get("results")
        if not results:
            raise ValueError(f"City not found: {city}")

        lat = float(results[0]["latitude"])
        lon = float(results[0]["longitude"])
        self._geo_cache[cache_key] = (time.monotonic(), (lat, lon))
        self._enforce_cache_limit(self._geo_cache)
        logger.debug("Geocoded '{}' → ({}, {})", city, lat, lon)
        return lat, lon

    # ------------------------------------------------------------------
    # Current weather
    # ------------------------------------------------------------------

    async def get_current(self, lat: float, lon: float) -> dict[str, Any]:
        """Fetch current weather conditions for the given coordinates.

        Args:
            lat: Latitude.
            lon: Longitude.

        Returns:
            A dict with keys: ``temperature``, ``feels_like``,
            ``humidity``, ``wind_speed``, ``condition``, ``uv_index``.
        """
        cache_key = f"current:{lat:.4f},{lon:.4f}"
        entry = self._weather_cache.get(cache_key)
        if self._is_cached(entry):
            return entry[1]  # type: ignore[index]

        data = await self._fetch_json(
            _FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "apparent_temperature,wind_speed_10m,"
                    "weather_code,uv_index"
                ),
                "timezone": "auto",
                **_UNIT_PARAMS.get(self._units, {}),
            },
        )

        current = data["current"]
        result: dict[str, Any] = {
            "temperature": current["temperature_2m"],
            "feels_like": current["apparent_temperature"],
            "humidity": current["relative_humidity_2m"],
            "wind_speed": current["wind_speed_10m"],
            "condition": _weather_code_text(current["weather_code"]),
            "uv_index": current["uv_index"],
        }

        self._weather_cache[cache_key] = (time.monotonic(), result)
        self._enforce_cache_limit(self._weather_cache)
        return result

    # ------------------------------------------------------------------
    # Daily forecast
    # ------------------------------------------------------------------

    async def get_forecast(
        self, lat: float, lon: float, days: int = 3,
    ) -> list[dict[str, Any]]:
        """Fetch a multi-day weather forecast.

        Args:
            lat: Latitude.
            lon: Longitude.
            days: Number of forecast days (1–7).

        Returns:
            A list of dicts, each with: ``date``, ``temp_max``,
            ``temp_min``, ``condition``, ``precipitation_prob``.
        """
        days = max(1, min(days, 16))

        cache_key = f"forecast:{lat:.4f},{lon:.4f}:{days}"
        entry = self._weather_cache.get(cache_key)
        if self._is_cached(entry):
            return entry[1]  # type: ignore[index]

        data = await self._fetch_json(
            _FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "weather_code,precipitation_probability_max"
                ),
                "forecast_days": days,
                "timezone": "auto",
                **_UNIT_PARAMS.get(self._units, {}),
            },
        )

        daily = data["daily"]
        result: list[dict[str, Any]] = []
        for i in range(len(daily["time"])):
            result.append({
                "date": daily["time"][i],
                "temp_max": daily["temperature_2m_max"][i],
                "temp_min": daily["temperature_2m_min"][i],
                "condition": _weather_code_text(daily["weather_code"][i]),
                "precipitation_prob": daily["precipitation_probability_max"][i],
            })

        self._weather_cache[cache_key] = (time.monotonic(), result)
        self._enforce_cache_limit(self._weather_cache)
        return result

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client and clear caches."""
        await self._http.aclose()
        self._geo_cache.clear()
        self._weather_cache.clear()
        logger.debug("WeatherClient closed")
