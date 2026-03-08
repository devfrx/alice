"""Tests for backend.plugins.news — NewsPlugin and FeedReader."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
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


def _make_feed_entry(
    title: str = "Test Article",
    summary: str = "Summary text",
    link: str = "https://example.com/article",
    published: str = "2026-03-08T10:00:00Z",
) -> SimpleNamespace:
    """Build a fake feedparser entry."""
    return SimpleNamespace(
        title=title,
        summary=summary,
        link=link,
        published=published,
    )


def _make_parsed_feed(entries: list | None = None) -> SimpleNamespace:
    """Build a fake feedparser.parse() result."""
    if entries is None:
        entries = [_make_feed_entry()]
    return SimpleNamespace(entries=entries)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> AppContext:
    cfg = load_config()
    return AppContext(config=cfg, event_bus=EventBus())


@pytest.fixture
def exec_context() -> ExecutionContext:
    return _make_exec_ctx()


@pytest.fixture
def plugin(ctx: AppContext):
    """Return an initialised NewsPlugin with a mocked FeedReader."""
    from backend.plugins.news.plugin import NewsPlugin

    p = NewsPlugin()
    p._ctx = ctx
    p._initialized = True
    p._reader = MagicMock()
    p._reader.fetch_all_feeds = AsyncMock(return_value=[])
    p._reader.fetch_feed = AsyncMock(return_value=[])
    p._reader.close = AsyncMock()
    return p


@pytest.fixture
def ctx_with_plugins(ctx: AppContext) -> AppContext:
    """AppContext with mock plugin_manager and tool_registry."""
    ctx.plugin_manager = MagicMock()
    ctx.tool_registry = MagicMock()
    ctx.tool_registry.execute_tool = AsyncMock()
    return ctx


@pytest.fixture
def plugin_with_plugins(ctx_with_plugins: AppContext):
    """NewsPlugin wired with mock plugin_manager + tool_registry."""
    from backend.plugins.news.plugin import NewsPlugin

    p = NewsPlugin()
    p._ctx = ctx_with_plugins
    p._initialized = True
    p._reader = MagicMock()
    p._reader.fetch_all_feeds = AsyncMock(return_value=[])
    p._reader.close = AsyncMock()
    return p


# ===================================================================
# 1. TestNewsPluginLifecycle
# ===================================================================


class TestNewsPluginLifecycle:
    """Plugin metadata, initialization, tools, cleanup, connection_status."""

    def test_plugin_attributes(self):
        from backend.plugins.news.plugin import NewsPlugin

        p = NewsPlugin()
        assert p.plugin_name == "news"
        assert p.plugin_priority == 15
        assert p.plugin_version == "1.0.0"
        assert p.plugin_dependencies == []

    @pytest.mark.asyncio
    async def test_initialize_creates_reader(self, ctx: AppContext):
        from backend.plugins.news.plugin import NewsPlugin

        p = NewsPlugin()
        with patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True):
            await p.initialize(ctx)

        assert p._reader is not None
        assert p.is_initialized
        # Cleanup
        await p.cleanup()

    def test_get_tools_returns_two(self, plugin):
        tools = plugin.get_tools()
        assert len(tools) == 2

    def test_tool_names(self, plugin):
        tools = plugin.get_tools()
        names = {t.name for t in tools}
        assert names == {"get_news", "get_daily_briefing"}

    def test_tool_risk_levels(self, plugin):
        tools = plugin.get_tools()
        for tool in tools:
            assert tool.risk_level == "safe"

    @pytest.mark.asyncio
    async def test_cleanup_closes_reader(self, plugin):
        reader_mock = plugin._reader
        await plugin.cleanup()
        reader_mock.close.assert_awaited_once()
        assert plugin._reader is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_connection_status_connected(self, plugin):
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", False)
    async def test_connection_status_disconnected_no_feedparser(self, plugin):
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_connection_status_disconnected_no_reader(self, ctx: AppContext):
        from backend.plugins.news.plugin import NewsPlugin

        p = NewsPlugin()
        p._ctx = ctx
        p._initialized = True
        p._reader = None
        status = await p.get_connection_status()
        assert status == ConnectionStatus.DISCONNECTED

    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", False)
    def test_check_dependencies_missing_feedparser(self, plugin):
        deps = plugin.check_dependencies()
        assert deps == ["feedparser"]

    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    def test_check_dependencies_all_ok(self, plugin):
        deps = plugin.check_dependencies()
        assert deps == []

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", False)
    async def test_execute_tool_feedparser_missing(self, plugin, exec_context):
        result = await plugin.execute_tool("get_news", {}, exec_context)
        assert not result.success
        assert "feedparser" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_execute_tool_unknown_tool(self, plugin, exec_context):
        with patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True):
            result = await plugin.execute_tool("nonexistent", {}, exec_context)
        assert not result.success
        assert "unknown" in (result.error_message or result.content or "").lower()


# ===================================================================
# 2. TestGetNewsTool
# ===================================================================


class TestGetNewsTool:
    """Tests for the get_news tool execution."""

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_fetch_all_configured_feeds(self, plugin, exec_context):
        articles = [
            {"title": "Article 1", "summary": "Sum 1", "link": "https://a.com/1",
             "published_iso": "", "source": "https://feed1.com/rss"},
            {"title": "Article 2", "summary": "Sum 2", "link": "https://a.com/2",
             "published_iso": "", "source": "https://feed2.com/rss"},
        ]
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=articles)

        result = await plugin.execute_tool("get_news", {}, exec_context)

        assert result.success
        plugin._reader.fetch_all_feeds.assert_awaited_once()
        call_kwargs = plugin._reader.fetch_all_feeds.call_args
        # feeds should match the config
        assert len(call_kwargs.kwargs.get("urls", call_kwargs[1].get("urls", []))) > 0 or len(call_kwargs[0][0]) > 0

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_topic_filter_case_insensitive(self, plugin, exec_context):
        articles = [
            {"title": "Python 3.14 Released", "summary": "New Python version",
             "link": "https://a.com/1", "published_iso": "", "source": "feed1"},
            {"title": "Weather Update", "summary": "Sunny day ahead",
             "link": "https://a.com/2", "published_iso": "", "source": "feed2"},
            {"title": "Java News", "summary": "Python interop added",
             "link": "https://a.com/3", "published_iso": "", "source": "feed3"},
        ]
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=articles)

        result = await plugin.execute_tool(
            "get_news", {"topic": "PYTHON"}, exec_context,
        )

        assert result.success
        data = result.content
        # Should match "Python" in title of article 1, summary of article 3
        assert data["total"] == 2
        titles = {a["title"] for a in data["articles"]}
        assert "Python 3.14 Released" in titles
        assert "Java News" in titles  # matched via summary
        assert "Weather Update" not in titles

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_max_results_limit(self, plugin, exec_context):
        articles = [
            {"title": f"Article {i}", "summary": "", "link": f"https://a.com/{i}",
             "published_iso": "", "source": "feed"}
            for i in range(20)
        ]
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=articles)

        result = await plugin.execute_tool(
            "get_news", {"max_results": 3}, exec_context,
        )

        assert result.success
        assert result.content["total"] == 3
        assert len(result.content["articles"]) == 3

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_default_max_results_from_config(self, plugin, exec_context):
        articles = [
            {"title": f"Art {i}", "summary": "", "link": f"https://a.com/{i}",
             "published_iso": "", "source": "feed"}
            for i in range(50)
        ]
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=articles)

        result = await plugin.execute_tool("get_news", {}, exec_context)

        assert result.success
        expected_max = plugin.ctx.config.news.max_articles
        assert result.content["total"] == expected_max

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_feed_unavailable_partial_results(self, plugin, exec_context):
        """If one feed fails, fetch_all_feeds still returns partial articles."""
        partial = [
            {"title": "Good Article", "summary": "OK", "link": "https://a.com/1",
             "published_iso": "", "source": "feed1"},
        ]
        # FeedReader.fetch_all_feeds already handles exceptions internally
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=partial)

        result = await plugin.execute_tool("get_news", {}, exec_context)

        assert result.success
        assert result.content["total"] == 1
        assert result.content["articles"][0]["title"] == "Good Article"

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_result_has_execution_time(self, plugin, exec_context):
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])

        result = await plugin.execute_tool("get_news", {}, exec_context)

        assert result.success
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_empty_feeds_return_empty(self, plugin, exec_context):
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])

        result = await plugin.execute_tool("get_news", {}, exec_context)

        assert result.success
        assert result.content["total"] == 0
        assert result.content["articles"] == []


# ===================================================================
# 3. TestGetDailyBriefingTool
# ===================================================================


class TestGetDailyBriefingTool:
    """Tests for the get_daily_briefing tool execution."""

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_full_briefing(self, plugin_with_plugins, exec_context):
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        news_articles = [
            {"title": f"News {i}", "summary": "", "link": f"https://a.com/{i}",
             "published_iso": "", "source": "feed"}
            for i in range(5)
        ]
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=news_articles)

        # Mock weather plugin present + connected
        weather_plugin = AsyncMock()
        weather_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )
        # Mock calendar plugin present + connected
        calendar_plugin = AsyncMock()
        calendar_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )

        def _get_plugin(name):
            if name == "weather":
                return weather_plugin
            if name == "calendar":
                return calendar_plugin
            return None

        ctx.plugin_manager.get_plugin = MagicMock(side_effect=_get_plugin)

        weather_data = {"temp": 22, "condition": "sunny"}
        calendar_data = [{"title": "Meeting", "time": "10:00"}]

        async def _execute_tool(name, args, context):
            if name == "weather_get_weather":
                return ToolResult.ok(content=weather_data)
            if name == "calendar_get_today_summary":
                return ToolResult.ok(content=calendar_data)
            return ToolResult.error("unknown")

        ctx.tool_registry.execute_tool = AsyncMock(side_effect=_execute_tool)

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        data = result.content
        assert "date_iso" in data
        assert data["weather"] == weather_data
        assert data["today_events"] == calendar_data
        assert len(data["top_news"]) == 5

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_weather_unavailable_graceful(
        self, plugin_with_plugins, exec_context,
    ):
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])

        # Weather plugin missing
        calendar_plugin = AsyncMock()
        calendar_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )

        def _get_plugin(name):
            if name == "weather":
                return None
            if name == "calendar":
                return calendar_plugin
            return None

        ctx.plugin_manager.get_plugin = MagicMock(side_effect=_get_plugin)
        ctx.tool_registry.execute_tool = AsyncMock(
            return_value=ToolResult.ok(content=[]),
        )

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["weather"] is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_calendar_unavailable_graceful(
        self, plugin_with_plugins, exec_context,
    ):
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])

        weather_plugin = AsyncMock()
        weather_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )

        def _get_plugin(name):
            if name == "weather":
                return weather_plugin
            if name == "calendar":
                return None
            return None

        ctx.plugin_manager.get_plugin = MagicMock(side_effect=_get_plugin)
        ctx.tool_registry.execute_tool = AsyncMock(
            return_value=ToolResult.ok(content={"temp": 20}),
        )

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["today_events"] is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_both_soft_deps_unavailable(
        self, plugin_with_plugins, exec_context,
    ):
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        news = [{"title": "Only News", "summary": "", "link": "https://a.com/1",
                 "published_iso": "", "source": "feed"}]
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=news)

        ctx.plugin_manager.get_plugin = MagicMock(return_value=None)

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        data = result.content
        assert data["weather"] is None
        assert data["today_events"] is None
        assert len(data["top_news"]) == 1
        assert "date_iso" in data

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_news_fetch_failure_partial_briefing(
        self, plugin_with_plugins, exec_context,
    ):
        """If news fetching raises, briefing returns empty top_news."""
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        plugin._reader.fetch_all_feeds = AsyncMock(
            side_effect=Exception("Feed timeout"),
        )

        ctx.plugin_manager.get_plugin = MagicMock(return_value=None)

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["top_news"] == []
        assert result.content["weather"] is None
        assert result.content["today_events"] is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_weather_tool_execution_fails(
        self, plugin_with_plugins, exec_context,
    ):
        """Weather tool returns an error result — briefing continues."""
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])

        weather_plugin = AsyncMock()
        weather_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )

        def _get_plugin(name):
            if name == "weather":
                return weather_plugin
            return None

        ctx.plugin_manager.get_plugin = MagicMock(side_effect=_get_plugin)
        ctx.tool_registry.execute_tool = AsyncMock(
            return_value=ToolResult.error("API timeout"),
        )

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        # Weather tool returned error ⇒ result.success=False ⇒ weather is None
        assert result.content["weather"] is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_weather_plugin_disconnected(
        self, plugin_with_plugins, exec_context,
    ):
        """Weather plugin exists but is disconnected — skip gracefully."""
        plugin = plugin_with_plugins
        ctx = plugin.ctx
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])

        weather_plugin = AsyncMock()
        weather_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.DISCONNECTED,
        )

        ctx.plugin_manager.get_plugin = MagicMock(
            side_effect=lambda n: weather_plugin if n == "weather" else None,
        )

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["weather"] is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_briefing_date_iso_present(
        self, plugin_with_plugins, exec_context,
    ):
        plugin = plugin_with_plugins
        plugin._reader.fetch_all_feeds = AsyncMock(return_value=[])
        plugin.ctx.plugin_manager.get_plugin = MagicMock(return_value=None)

        result = await plugin.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert "date_iso" in result.content
        # ISO format should contain 'T'
        assert "T" in result.content["date_iso"]


# ===================================================================
# 4. TestFeedReader
# ===================================================================


class TestFeedReader:
    """Tests for FeedReader: fetch, cache, SSRF, error handling."""

    @pytest.fixture
    def reader(self):
        from backend.plugins.news.feed_reader import FeedReader

        return FeedReader(cache_ttl_minutes=15)

    @pytest.mark.asyncio
    async def test_fetch_feed_parse_and_normalise(self, reader):
        """fetch_feed parses RSS XML and normalises articles."""
        entries = [
            _make_feed_entry("Title A", "Sum A", "https://a.com/1", "2026-03-01"),
            _make_feed_entry("Title B", "Sum B", "https://a.com/2", "2026-03-02"),
        ]
        parsed = _make_parsed_feed(entries)

        mock_response = AsyncMock()
        mock_response.text = "<rss>fake</rss>"
        mock_response.raise_for_status = MagicMock()

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=AsyncMock(return_value=mock_response)),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = parsed

            articles = await reader.fetch_feed("https://example.com/rss")

        assert len(articles) == 2
        assert articles[0]["title"] == "Title A"
        assert articles[0]["source"] == "https://example.com/rss"
        assert articles[1]["link"] == "https://a.com/2"
        assert "published_iso" in articles[0]

    @pytest.mark.asyncio
    async def test_fetch_feed_max_articles(self, reader):
        entries = [_make_feed_entry(f"Art {i}") for i in range(20)]
        parsed = _make_parsed_feed(entries)

        mock_response = AsyncMock()
        mock_response.text = "<rss/>"
        mock_response.raise_for_status = MagicMock()

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=AsyncMock(return_value=mock_response)),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = parsed

            articles = await reader.fetch_feed("https://example.com/rss", max_articles=5)

        assert len(articles) == 5

    @pytest.mark.asyncio
    async def test_fetch_all_feeds_parallel(self, reader):
        """fetch_all_feeds calls multiple feeds and merges results."""
        entries_a = [_make_feed_entry("From A")]
        entries_b = [_make_feed_entry("From B")]

        call_count = 0

        async def _mock_fetch(url, max_articles=10, timeout_s=10):
            nonlocal call_count
            call_count += 1
            if "feed_a" in url:
                return [{"title": "From A", "summary": "", "link": "", "published_iso": "", "source": url}]
            return [{"title": "From B", "summary": "", "link": "", "published_iso": "", "source": url}]

        with patch.object(reader, "fetch_feed", side_effect=_mock_fetch):
            articles = await reader.fetch_all_feeds(
                ["https://feed_a.com/rss", "https://feed_b.com/rss"],
            )

        assert call_count == 2
        assert len(articles) == 2
        titles = {a["title"] for a in articles}
        assert titles == {"From A", "From B"}

    @pytest.mark.asyncio
    async def test_fetch_all_feeds_one_fails_partial(self, reader):
        """If one feed fails, other feeds still return their articles."""

        async def _mock_fetch(url, max_articles=10, timeout_s=10):
            if "bad" in url:
                raise ConnectionError("DNS failed")
            return [{"title": "Good", "summary": "", "link": "", "published_iso": "", "source": url}]

        with patch.object(reader, "fetch_feed", side_effect=_mock_fetch):
            articles = await reader.fetch_all_feeds(
                ["https://bad.com/rss", "https://good.com/rss"],
            )

        assert len(articles) == 1
        assert articles[0]["title"] == "Good"

    @pytest.mark.asyncio
    async def test_caching_single_http_request(self, reader):
        """Calling fetch_feed twice uses cache — only 1 HTTP call."""
        entries = [_make_feed_entry("Cached Article")]
        parsed = _make_parsed_feed(entries)

        mock_response = AsyncMock()
        mock_response.text = "<rss/>"
        mock_response.raise_for_status = MagicMock()

        mock_get = AsyncMock(return_value=mock_response)

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=mock_get),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = parsed

            result1 = await reader.fetch_feed("https://example.com/rss")
            result2 = await reader.fetch_feed("https://example.com/rss")

        # Only 1 HTTP call — second read from cache
        assert mock_get.await_count == 1
        assert len(result1) == 1
        assert len(result2) == 1

    @pytest.mark.asyncio
    async def test_cache_ttl_expiry(self, reader):
        """After TTL expires, cache is invalidated and a new fetch occurs."""
        entries = [_make_feed_entry("Fresh")]
        parsed = _make_parsed_feed(entries)

        mock_response = AsyncMock()
        mock_response.text = "<rss/>"
        mock_response.raise_for_status = MagicMock()
        mock_get = AsyncMock(return_value=mock_response)

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=mock_get),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = parsed

            # First call
            await reader.fetch_feed("https://example.com/rss")
            assert mock_get.await_count == 1

            # Manually expire the cache by setting the timestamp far in the past
            url = "https://example.com/rss"
            ts, articles = reader._cache[url]
            reader._cache[url] = (ts - reader._cache_ttl_s - 1, articles)

            # Second call — cache expired, should fetch again
            await reader.fetch_feed("https://example.com/rss")
            assert mock_get.await_count == 2

    @pytest.mark.asyncio
    async def test_ssrf_validation_on_every_fetch(self, reader):
        """validate_url_ssrf is called for each fetch_feed call."""
        entries = [_make_feed_entry()]
        parsed = _make_parsed_feed(entries)

        mock_response = AsyncMock()
        mock_response.text = "<rss/>"
        mock_response.raise_for_status = MagicMock()

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=AsyncMock(return_value=mock_response)),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf") as mock_ssrf,
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = parsed

            await reader.fetch_feed("https://example.com/rss")

        mock_ssrf.assert_called_once_with("https://example.com/rss")

    @pytest.mark.asyncio
    async def test_ssrf_blocks_private_url(self, reader):
        """SSRF validation rejects private/localhost URLs."""
        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch(
                "backend.plugins.news.feed_reader.validate_url_ssrf",
                side_effect=ValueError("SSRF: blocked URL"),
            ),
        ):
            with pytest.raises(ValueError, match="SSRF"):
                await reader.fetch_feed("http://127.0.0.1/secret")

    @pytest.mark.asyncio
    async def test_feedparser_error_handling(self, reader):
        """feedparser raising an exception propagates from fetch_feed."""
        mock_response = AsyncMock()
        mock_response.text = "<invalid>"
        mock_response.raise_for_status = MagicMock()

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=AsyncMock(return_value=mock_response)),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.side_effect = Exception("Parse error")

            with pytest.raises(Exception, match="Parse error"):
                await reader.fetch_feed("https://example.com/rss")

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, reader):
        """HTTP errors from the client propagate correctly."""
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response,
        )

        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(reader._client, "get", new=AsyncMock(return_value=mock_response)),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await reader.fetch_feed("https://example.com/rss")

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self, reader):
        with patch.object(reader._client, "aclose", new=AsyncMock()) as mock_aclose:
            await reader.close()
        mock_aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_normalise_entry_truncates_summary(self, reader):
        """Summaries longer than 500 chars are truncated."""
        from backend.plugins.news.feed_reader import FeedReader

        long_summary = "x" * 1000
        entry = _make_feed_entry(summary=long_summary)
        normalised = FeedReader._normalise_entry(entry, "https://feed.com")
        assert len(normalised["summary"]) == 500

    @pytest.mark.asyncio
    async def test_normalise_entry_missing_fields(self, reader):
        """Entries with missing attributes return empty strings."""
        from backend.plugins.news.feed_reader import FeedReader

        entry = SimpleNamespace()  # No attributes at all
        normalised = FeedReader._normalise_entry(entry, "https://feed.com")
        assert normalised["title"] == ""
        assert normalised["summary"] == ""
        assert normalised["link"] == ""
        assert normalised["published_iso"] == ""
        assert normalised["source"] == "https://feed.com"

    @pytest.mark.asyncio
    async def test_feedparser_not_available(self):
        """FeedReader raises RuntimeError if feedparser is missing."""
        with patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", False):
            from backend.plugins.news.feed_reader import FeedReader

            reader = FeedReader()
            with pytest.raises(RuntimeError, match="feedparser"):
                await reader.fetch_feed("https://example.com/rss")

    @pytest.mark.asyncio
    async def test_cache_eviction_at_max_size(self, reader):
        """Cache evicts oldest entry when at max capacity."""
        from backend.plugins.news.feed_reader import FeedReader

        # Fill cache to max
        for i in range(FeedReader._MAX_CACHE_SIZE):
            url = f"https://feed{i}.com/rss"
            reader._cache[url] = (time.monotonic(), [{"title": f"Art {i}"}])

        assert len(reader._cache) == FeedReader._MAX_CACHE_SIZE
        first_url = next(iter(reader._cache))

        # Add one more entry via fetch_feed
        entries = [_make_feed_entry("New Article")]
        parsed = _make_parsed_feed(entries)

        mock_response = AsyncMock()
        mock_response.text = "<rss/>"
        mock_response.raise_for_status = MagicMock()

        new_url = "https://brand-new-feed.com/rss"
        with (
            patch("backend.plugins.news.feed_reader._FEEDPARSER_AVAILABLE", True),
            patch.object(
                reader._client, "get", new=AsyncMock(return_value=mock_response),
            ),
            patch("backend.plugins.news.feed_reader.validate_url_ssrf"),
            patch("backend.plugins.news.feed_reader.feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = parsed
            await reader.fetch_feed(new_url)

        # Size should still be at max
        assert len(reader._cache) == FeedReader._MAX_CACHE_SIZE
        # Oldest entry should have been evicted
        assert first_url not in reader._cache
        # New entry should be present
        assert new_url in reader._cache


# ===================================================================
# 5. TestSoftDependencies
# ===================================================================


class TestSoftDependencies:
    """Plugin doesn't crash when weather/calendar plugins are absent."""

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_no_plugin_manager(self, exec_context):
        """Briefing works when plugin_manager is None."""
        from backend.plugins.news.plugin import NewsPlugin

        ctx = AppContext(config=load_config(), event_bus=EventBus())
        assert ctx.plugin_manager is None

        p = NewsPlugin()
        p._ctx = ctx
        p._initialized = True
        p._reader = MagicMock()
        p._reader.fetch_all_feeds = AsyncMock(return_value=[
            {"title": "News", "summary": "", "link": "", "published_iso": "", "source": "feed"},
        ])

        result = await p.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        data = result.content
        assert data["weather"] is None
        assert data["today_events"] is None
        assert len(data["top_news"]) == 1

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_weather_and_calendar_not_loaded(self, exec_context):
        """Briefing works when plugin_manager exists but plugins aren't registered."""
        ctx = AppContext(config=load_config(), event_bus=EventBus())
        ctx.plugin_manager = MagicMock()
        ctx.plugin_manager.get_plugin = MagicMock(return_value=None)

        from backend.plugins.news.plugin import NewsPlugin

        p = NewsPlugin()
        p._ctx = ctx
        p._initialized = True
        p._reader = MagicMock()
        p._reader.fetch_all_feeds = AsyncMock(return_value=[
            {"title": "Solo News", "summary": "", "link": "", "published_iso": "", "source": "f"},
        ])

        result = await p.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["weather"] is None
        assert result.content["today_events"] is None
        assert result.content["top_news"][0]["title"] == "Solo News"

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_weather_raises_exception_graceful(self, exec_context):
        """If weather tool call throws, briefing continues without weather."""
        ctx = AppContext(config=load_config(), event_bus=EventBus())
        ctx.plugin_manager = MagicMock()
        ctx.tool_registry = MagicMock()

        weather_plugin = AsyncMock()
        weather_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )

        ctx.plugin_manager.get_plugin = MagicMock(
            side_effect=lambda n: weather_plugin if n == "weather" else None,
        )
        ctx.tool_registry.execute_tool = AsyncMock(
            side_effect=Exception("Weather API crashed"),
        )

        from backend.plugins.news.plugin import NewsPlugin

        p = NewsPlugin()
        p._ctx = ctx
        p._initialized = True
        p._reader = MagicMock()
        p._reader.fetch_all_feeds = AsyncMock(return_value=[])

        result = await p.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["weather"] is None

    @pytest.mark.asyncio
    @patch("backend.plugins.news.plugin._FEEDPARSER_AVAILABLE", True)
    async def test_calendar_raises_exception_graceful(self, exec_context):
        """If calendar tool call throws, briefing continues without events."""
        ctx = AppContext(config=load_config(), event_bus=EventBus())
        ctx.plugin_manager = MagicMock()
        ctx.tool_registry = MagicMock()

        calendar_plugin = AsyncMock()
        calendar_plugin.get_connection_status = AsyncMock(
            return_value=ConnectionStatus.CONNECTED,
        )

        ctx.plugin_manager.get_plugin = MagicMock(
            side_effect=lambda n: calendar_plugin if n == "calendar" else None,
        )
        ctx.tool_registry.execute_tool = AsyncMock(
            side_effect=Exception("Calendar DB error"),
        )

        from backend.plugins.news.plugin import NewsPlugin

        p = NewsPlugin()
        p._ctx = ctx
        p._initialized = True
        p._reader = MagicMock()
        p._reader.fetch_all_feeds = AsyncMock(return_value=[])

        result = await p.execute_tool("get_daily_briefing", {}, exec_context)

        assert result.success
        assert result.content["today_events"] is None
