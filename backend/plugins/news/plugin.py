"""AL\\CE — News/briefing plugin.

Provides ``get_news`` and ``get_daily_briefing`` tools for fetching
RSS feeds and building a daily summary (with optional soft dependencies
on weather and calendar plugins).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.news.feed_reader import FeedReader, _FEEDPARSER_AVAILABLE

if TYPE_CHECKING:
    from backend.core.context import AppContext


class NewsPlugin(BasePlugin):
    """RSS news feeds and daily briefing aggregator."""

    plugin_name: str = "news"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "RSS news feeds and daily briefing aggregator."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 15

    # Cross-plugin tool names follow the convention {plugin_name}_{tool_name}
    _WEATHER_TOOL = "weather_get_weather"
    _CALENDAR_TOOL = "calendar_get_today_summary"

    def __init__(self) -> None:
        super().__init__()
        self._reader: FeedReader | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Create the feed reader with config-driven TTL.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        cache_ttl = ctx.config.news.cache_ttl_minutes
        self._reader = FeedReader(cache_ttl_minutes=cache_ttl)
        if not _FEEDPARSER_AVAILABLE:
            logger.warning(
                "news plugin: feedparser not installed — tools will be unavailable"
            )

    async def cleanup(self) -> None:
        """Close the feed reader HTTP client."""
        if self._reader is not None:
            await self._reader.close()
            self._reader = None
        await super().cleanup()

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for news retrieval and daily briefing.

        Returns:
            A list of two ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="get_news",
                description=(
                    "Fetch recent news articles from configured RSS feeds. "
                    "Optionally filter by topic keyword and language."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": (
                                "Filter articles whose title or summary "
                                "contains this keyword (case-insensitive)."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum articles to return (default 10).",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=20_000,
            ),
            ToolDefinition(
                name="get_daily_briefing",
                description=(
                    "Build a daily briefing with current date/time, "
                    "top news headlines, weather (if available) and "
                    "today's calendar events (if available)."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="safe",
                timeout_ms=30_000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested tool.

        Args:
            tool_name: ``"get_news"`` or ``"get_daily_briefing"``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the JSON payload or an error.
        """
        if not _FEEDPARSER_AVAILABLE:
            return ToolResult.error("feedparser is not installed")
        if self._reader is None:
            return ToolResult.error("News plugin not initialised")

        start = time.perf_counter()

        try:
            if tool_name == "get_news":
                result = await self._execute_get_news(args)
            elif tool_name == "get_daily_briefing":
                result = await self._execute_get_daily_briefing(context)
            else:
                return ToolResult.error(f"Unknown tool: {tool_name}")
        except Exception as exc:
            self.logger.error("Tool {} failed: {}", tool_name, exc)
            return ToolResult.error(str(exc))

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=result,
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # Dependency / health
    # ------------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list with ``"feedparser"`` if the package is not installed,
            otherwise an empty list.
        """
        if not _FEEDPARSER_AVAILABLE:
            return ["feedparser"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if feedparser is available.

        Returns:
            ``ConnectionStatus.CONNECTED`` or ``ConnectionStatus.DISCONNECTED``.
        """
        if _FEEDPARSER_AVAILABLE and self._reader is not None:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.DISCONNECTED

    # ------------------------------------------------------------------
    # Private: get_news
    # ------------------------------------------------------------------

    async def _execute_get_news(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch news from all configured feeds, optionally filtering.

        Args:
            args: Tool arguments (topic, max_results).

        Returns:
            Dict with articles list and total count.
        """
        if self._reader is None:
            raise RuntimeError("News plugin not initialized")

        cfg = self.ctx.config.news
        topic: str | None = args.get("topic")
        max_results: int = args.get("max_results", cfg.max_articles)

        articles = await self._reader.fetch_all_feeds(
            urls=list(cfg.feeds),
            max_per_feed=cfg.max_articles,
            timeout_s=cfg.request_timeout_s,
        )

        # Filter by topic if provided
        if topic:
            topic_lower = topic.lower()
            articles = [
                a for a in articles
                if topic_lower in (a.get("title", "") or "").lower()
                or topic_lower in (a.get("summary", "") or "").lower()
            ]

        # Limit results
        articles = articles[:max_results]

        return {
            "articles": articles,
            "total": len(articles),
        }

    # ------------------------------------------------------------------
    # Private: get_daily_briefing
    # ------------------------------------------------------------------

    async def _execute_get_daily_briefing(
        self,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Build a daily briefing aggregating news + soft dependencies.

        Args:
            context: Execution context for cross-plugin tool calls.

        Returns:
            Dict with date_iso, weather, today_events, and top_news.
        """
        if self._reader is None:
            raise RuntimeError("News plugin not initialized")

        cfg = self.ctx.config.news
        now = datetime.now(tz=timezone.utc)

        # 1. Top news
        try:
            articles = await self._reader.fetch_all_feeds(
                urls=list(cfg.feeds),
                max_per_feed=cfg.max_articles,
                timeout_s=cfg.request_timeout_s,
            )
            top_news = articles[:5]
        except Exception:
            self.logger.warning("News fetch failed for daily briefing")
            top_news = []

        # 2. Weather (soft dependency)
        weather_data = await self._try_weather(context)

        # 3. Calendar (soft dependency)
        today_events = await self._try_calendar(context)

        return {
            "date_iso": now.isoformat(),
            "weather": weather_data,
            "today_events": today_events,
            "top_news": top_news,
        }

    async def _try_weather(
        self,
        context: ExecutionContext,
    ) -> dict[str, Any] | None:
        """Attempt to fetch weather data from the weather plugin.

        Returns None silently if the plugin is unavailable or fails.

        Args:
            context: Execution context for cross-plugin calls.

        Returns:
            Weather dict or None.
        """
        if not self.ctx.plugin_manager:
            return None
        if not self.ctx.tool_registry:
            return None

        weather_plugin = self.ctx.plugin_manager.get_plugin("weather")
        if weather_plugin is None:
            return None

        try:
            status = await weather_plugin.get_connection_status()
            if status not in (ConnectionStatus.CONNECTED, ConnectionStatus.UNKNOWN):
                return None

            result = await self.ctx.tool_registry.execute_tool(
                self._WEATHER_TOOL, {}, context,
            )
            if result.success:
                return result.content
        except Exception:
            self.logger.debug("Weather soft-dep failed, skipping")

        return None

    async def _try_calendar(
        self,
        context: ExecutionContext,
    ) -> list[dict[str, Any]] | None:
        """Attempt to fetch today's events from the calendar plugin.

        Returns None silently if the plugin is unavailable or fails.

        Args:
            context: Execution context for cross-plugin calls.

        Returns:
            List of event dicts or None.
        """
        if not self.ctx.plugin_manager:
            return None
        if not self.ctx.tool_registry:
            return None

        calendar_plugin = self.ctx.plugin_manager.get_plugin("calendar")
        if calendar_plugin is None:
            return None

        try:
            status = await calendar_plugin.get_connection_status()
            if status not in (ConnectionStatus.CONNECTED, ConnectionStatus.UNKNOWN):
                return None

            result = await self.ctx.tool_registry.execute_tool(
                self._CALENDAR_TOOL, {}, context,
            )
            if result.success:
                return result.content
        except Exception:
            self.logger.debug("Calendar soft-dep failed, skipping")

        return None
