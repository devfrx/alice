"""Tests for the Web Search plugin (web_search + web_scrape).

Covers plugin lifecycle, tool definitions, search execution with caching
and rate limiting, scrape execution with SSRF validation, and the
WebSearchClient helper class.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)


def _patched_async_client(**kwargs):
    """Create httpx.AsyncClient stripping unsupported ``proxy`` kwarg."""
    kwargs.pop("proxy", None)
    return _OriginalAsyncClient(**kwargs)


_OriginalAsyncClient = httpx.AsyncClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_httpx_proxies():
    """Strip unsupported ``proxy`` kwarg from httpx.AsyncClient in tests."""
    with patch(
        "backend.plugins.web_search.client.httpx.AsyncClient",
        side_effect=_patched_async_client,
    ):
        yield


@pytest.fixture
def ctx() -> AppContext:
    """Minimal AppContext with real config and fresh EventBus."""
    return AppContext(config=load_config(), event_bus=EventBus())


@pytest.fixture
def exec_context() -> ExecutionContext:
    """Standard execution context for tool invocations."""
    return ExecutionContext(
        session_id="test-session",
        conversation_id="test-conv-id",
        execution_id="test-exec-id",
    )


def _get_plugin():
    """Import and return WebSearchPlugin (lazy to avoid import errors)."""
    from backend.plugins.web_search.plugin import WebSearchPlugin

    return WebSearchPlugin()


def _fake_ddg_results(n: int = 3) -> list[dict[str, str]]:
    """Generate *n* fake DDG search result dicts."""
    return [
        {
            "title": f"Result {i}",
            "href": f"https://example.com/{i}",
            "body": f"Snippet for result {i}",
        }
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# Expected tool catalogue
# ---------------------------------------------------------------------------

EXPECTED_TOOLS: dict[str, dict] = {
    "web_search": {"risk": "safe", "confirm": False},
    "web_scrape": {"risk": "medium", "confirm": False},
}


# ---------------------------------------------------------------------------
# TestWebSearchPluginLifecycle
# ---------------------------------------------------------------------------


class TestWebSearchPluginLifecycle:
    """Plugin attributes, initialisation and tool discovery."""

    def test_plugin_attributes(self):
        """plugin_name, version, priority and description are set."""
        plugin = _get_plugin()
        assert plugin.plugin_name == "web_search"
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_priority == 40
        assert plugin.plugin_description

    @pytest.mark.asyncio
    async def test_initialize(self, ctx: AppContext):
        """Plugin initialises with AppContext and creates _client."""
        plugin = _get_plugin()
        assert not plugin.is_initialized
        await plugin.initialize(ctx)
        assert plugin.is_initialized
        assert plugin.ctx is ctx
        assert hasattr(plugin, "_client")
        await plugin.cleanup()

    def test_get_tools_count_and_names(self):
        """get_tools returns exactly 2 tools with correct names."""
        plugin = _get_plugin()
        tools = plugin.get_tools()
        assert len(tools) == len(EXPECTED_TOOLS)
        tool_names = {t.name for t in tools}
        assert tool_names == set(EXPECTED_TOOLS)

    def test_get_tools_risk_levels(self):
        """Each tool has the expected risk_level and requires_confirmation."""
        plugin = _get_plugin()
        tools = plugin.get_tools()
        by_name = {t.name: t for t in tools}
        for name, expected in EXPECTED_TOOLS.items():
            tool = by_name[name]
            assert tool.risk_level == expected["risk"], f"{name} risk mismatch"
            assert tool.requires_confirmation == expected["confirm"], (
                f"{name} confirm mismatch"
            )

    @pytest.mark.asyncio
    async def test_check_dependencies_ddgs_available(self):
        """When DDGS is importable, check_dependencies returns []."""
        plugin = _get_plugin()
        with patch("backend.plugins.web_search.plugin._DDGS_AVAILABLE", True):
            assert plugin.check_dependencies() == []

    @pytest.mark.asyncio
    async def test_check_dependencies_ddgs_missing(self):
        """When DDGS is missing, check_dependencies flags it."""
        plugin = _get_plugin()
        with patch("backend.plugins.web_search.plugin._DDGS_AVAILABLE", False):
            deps = plugin.check_dependencies()
            assert "ddgs" in deps

    @pytest.mark.asyncio
    async def test_connection_status_connected(self):
        """Status is CONNECTED when DDGS library is available."""
        plugin = _get_plugin()
        with patch("backend.plugins.web_search.plugin._DDGS_AVAILABLE", True):
            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_connection_status_error(self):
        """Status is ERROR when DDGS library is missing."""
        plugin = _get_plugin()
        with patch("backend.plugins.web_search.plugin._DDGS_AVAILABLE", False):
            status = await plugin.get_connection_status()
            assert status == ConnectionStatus.ERROR

    @pytest.mark.asyncio
    async def test_cleanup_closes_client(self, ctx: AppContext):
        """cleanup() calls close() on the underlying client."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)
        close_mock = AsyncMock()
        plugin._client.close = close_mock
        await plugin.cleanup()
        close_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, ctx: AppContext, exec_context: ExecutionContext):
        """Dispatching an unknown tool name returns an error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)
        result = await plugin.execute_tool("nonexistent", {}, exec_context)
        assert not result.success
        assert "Unknown tool" in result.error_message
        await plugin.cleanup()


# ---------------------------------------------------------------------------
# TestWebSearchTool
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    """web_search tool execution with mocked DDGS."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, ctx: AppContext, exec_context: ExecutionContext):
        """A successful search returns JSON results with query echo."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        fake = _fake_ddg_results(3)
        with patch.object(plugin._client, "search", new_callable=AsyncMock, return_value=fake):
            result = await plugin.execute_tool(
                "web_search", {"query": "python asyncio"}, exec_context,
            )

        assert result.success
        assert result.content["query"] == "python asyncio"
        assert len(result.content["results"]) == 3
        assert result.content_type == "application/json"
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_search_empty_query_error(self, ctx: AppContext, exec_context: ExecutionContext):
        """An empty query returns an error without calling the client."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool("web_search", {"query": ""}, exec_context)

        assert not result.success
        assert "Missing required parameter" in result.error_message
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_search_missing_query_error(self, ctx: AppContext, exec_context: ExecutionContext):
        """Missing query key returns an error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool("web_search", {}, exec_context)

        assert not result.success
        assert "query" in result.error_message.lower()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_search_max_results_clamped(self, ctx: AppContext, exec_context: ExecutionContext):
        """Invalid max_results values fall back to default (5)."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        mock_search = AsyncMock(return_value=_fake_ddg_results(5))
        with patch.object(plugin._client, "search", mock_search):
            # max_results=0 is out of [1,20] → clamped to 5
            await plugin.execute_tool(
                "web_search", {"query": "test", "max_results": 0}, exec_context,
            )
            mock_search.assert_awaited_once_with("test", 5)

            mock_search.reset_mock()
            # max_results=100 is out of [1,20] → clamped to 5
            await plugin.execute_tool(
                "web_search", {"query": "test", "max_results": 100}, exec_context,
            )
            mock_search.assert_awaited_once_with("test", 5)

            mock_search.reset_mock()
            # max_results="text" is not int → clamped to 5
            await plugin.execute_tool(
                "web_search", {"query": "test", "max_results": "bad"}, exec_context,
            )
            mock_search.assert_awaited_once_with("test", 5)

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_search_valid_max_results(self, ctx: AppContext, exec_context: ExecutionContext):
        """Valid max_results in [1,20] is forwarded to client."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        mock_search = AsyncMock(return_value=_fake_ddg_results(10))
        with patch.object(plugin._client, "search", mock_search):
            await plugin.execute_tool(
                "web_search", {"query": "test", "max_results": 10}, exec_context,
            )
            mock_search.assert_awaited_once_with("test", 10)

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_search_runtime_error_propagated(
        self, ctx: AppContext, exec_context: ExecutionContext,
    ):
        """RuntimeError from client (DDG missing) → ToolResult.error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        with patch.object(
            plugin._client, "search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ddgs is not installed"),
        ):
            result = await plugin.execute_tool(
                "web_search", {"query": "test"}, exec_context,
            )

        assert not result.success
        assert "not installed" in result.error_message
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_search_generic_error(self, ctx: AppContext, exec_context: ExecutionContext):
        """Generic exception from client → ToolResult.error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        with patch.object(
            plugin._client, "search",
            new_callable=AsyncMock,
            side_effect=Exception("network timeout"),
        ):
            result = await plugin.execute_tool(
                "web_search", {"query": "test"}, exec_context,
            )

        assert not result.success
        assert "Search failed" in result.error_message
        await plugin.cleanup()


# ---------------------------------------------------------------------------
# TestWebScrapeTool
# ---------------------------------------------------------------------------


class TestWebScrapeTool:
    """web_scrape tool execution with mocked httpx and SSRF validation."""

    @pytest.mark.asyncio
    async def test_scrape_returns_text(self, ctx: AppContext, exec_context: ExecutionContext):
        """A successful scrape returns plain text content."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        with patch.object(
            plugin._client, "scrape",
            new_callable=AsyncMock,
            return_value="Hello World article text",
        ):
            result = await plugin.execute_tool(
                "web_scrape", {"url": "https://example.com/article"}, exec_context,
            )

        assert result.success
        assert result.content == "Hello World article text"
        assert result.content_type == "text/plain"
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_scrape_empty_url_error(self, ctx: AppContext, exec_context: ExecutionContext):
        """Empty URL returns an error without calling the client."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool("web_scrape", {"url": ""}, exec_context)

        assert not result.success
        assert "Missing required parameter" in result.error_message
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_scrape_missing_url_error(self, ctx: AppContext, exec_context: ExecutionContext):
        """Missing url key returns an error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool("web_scrape", {}, exec_context)

        assert not result.success
        assert "url" in result.error_message.lower()
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_scrape_ssrf_blocked(self, ctx: AppContext, exec_context: ExecutionContext):
        """SSRF validation failure → ToolResult.error with 'URL blocked'."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        with patch.object(
            plugin._client, "scrape",
            new_callable=AsyncMock,
            side_effect=ValueError("resolves to private address 127.0.0.1"),
        ):
            result = await plugin.execute_tool(
                "web_scrape", {"url": "http://localhost/secret"}, exec_context,
            )

        assert not result.success
        assert "URL blocked" in result.error_message
        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_scrape_generic_error(self, ctx: AppContext, exec_context: ExecutionContext):
        """Generic exception from client → ToolResult.error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        with patch.object(
            plugin._client, "scrape",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            result = await plugin.execute_tool(
                "web_scrape", {"url": "https://example.com"}, exec_context,
            )

        assert not result.success
        assert "Scrape failed" in result.error_message
        await plugin.cleanup()


# ---------------------------------------------------------------------------
# TestWebSearchClient
# ---------------------------------------------------------------------------


class TestWebSearchClient:
    """Unit tests for the WebSearchClient helper class."""

    def _make_client(self, **kwargs):
        """Create a WebSearchClient with short limits for testing."""
        from backend.plugins.web_search.client import WebSearchClient

        defaults = {
            "max_results": 5,
            "cache_ttl_s": 300,
            "request_timeout_s": 10,
            "rate_limit_s": 0.0,  # disable rate limiting in tests
        }
        defaults.update(kwargs)
        return WebSearchClient(**defaults)

    @pytest.mark.asyncio
    async def test_client_init_defaults(self):
        """Client initialises with expected defaults."""
        client = self._make_client()
        assert client._max_results == 5
        assert client._cache_ttl_s == 300
        assert client._rate_limit_s == 0.0
        assert client._cache == {}
        await client.close()

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        """close() delegates to the underlying httpx client's aclose()."""
        client = self._make_client()
        client._http = AsyncMock()
        await client.close()
        client._http.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_calls_metasearch_via_to_thread(self):
        """search() runs _metasearch_sync in a thread and returns results."""
        client = self._make_client()
        fake = _fake_ddg_results(3)

        with patch(
            "backend.plugins.web_search.client.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=fake,
        ) as mock_thread:
            results = await client.search("python asyncio", max_results=3)

        mock_thread.assert_awaited_once_with(client._metasearch_sync, "python asyncio", 3, client._region, client._proxy_url)
        assert results == fake
        await client.close()

    @pytest.mark.asyncio
    async def test_search_cache_hit(self):
        """Second identical search returns cached results without DDGS call."""
        client = self._make_client()
        fake = _fake_ddg_results(3)

        with patch(
            "backend.plugins.web_search.client.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=fake,
        ) as mock_thread:
            first = await client.search("cached query", max_results=3)
            second = await client.search("cached query", max_results=3)

        # DDGS should be called only once → cache hit on second call
        mock_thread.assert_awaited_once()
        assert first == second == fake
        await client.close()

    @pytest.mark.asyncio
    async def test_search_cache_ttl_expiry(self):
        """Expired cache entry triggers a fresh DDGS search."""
        client = self._make_client(cache_ttl_s=60)
        fake = _fake_ddg_results(2)

        monotonic_base = 1000.0

        with (
            patch(
                "backend.plugins.web_search.client.asyncio.to_thread",
                new_callable=AsyncMock,
                return_value=fake,
            ) as mock_thread,
            patch(
                "backend.plugins.web_search.client.time.monotonic",
            ) as mock_mono,
        ):
            # First call at t=1000
            mock_mono.return_value = monotonic_base
            await client.search("expire test")

            # Second call at t=1100 (100s later, TTL=60 → expired)
            mock_mono.return_value = monotonic_base + 100
            await client.search("expire test")

        # DDGS called twice: first miss + second miss (cache expired)
        assert mock_thread.await_count == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_search_cache_eviction_at_max_size(self):
        """Oldest cache entry is evicted when _MAX_CACHE_SIZE is reached."""
        from backend.plugins.web_search.client import _MAX_CACHE_SIZE

        client = self._make_client()
        fake = _fake_ddg_results(1)

        with patch(
            "backend.plugins.web_search.client.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=fake,
        ):
            # Fill cache to max
            for i in range(_MAX_CACHE_SIZE):
                await client.search(f"query-{i}", max_results=1)

            assert len(client._cache) == _MAX_CACHE_SIZE

            # One more entry should evict the oldest
            first_key = next(iter(client._cache))
            await client.search("overflow-query", max_results=1)

            assert len(client._cache) == _MAX_CACHE_SIZE
            assert first_key not in client._cache

        await client.close()

    @pytest.mark.asyncio
    async def test_search_ddgs_not_available(self):
        """search() raises RuntimeError when DDGS is not installed."""
        client = self._make_client()

        with patch("backend.plugins.web_search.client._DDGS_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="not installed"):
                await client.search("test")

        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limiting_enforces_delay(self):
        """Rate limiter waits when calls are too close together."""
        client = self._make_client(rate_limit_s=1.0)
        fake = _fake_ddg_results(1)

        with (
            patch(
                "backend.plugins.web_search.client.asyncio.to_thread",
                new_callable=AsyncMock,
                return_value=fake,
            ),
            patch(
                "backend.plugins.web_search.client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            # First search sets _last_search_ts
            await client.search("query1")
            # Second search (different query) triggers rate limit
            await client.search("query2")

        # asyncio.sleep should have been called at least once for rate limiting
        assert mock_sleep.await_count >= 1
        await client.close()

    @pytest.mark.asyncio
    async def test_scrape_html_parsing(self):
        """scrape() extracts text from HTML, removing script/style tags."""
        client = self._make_client()

        html = (
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert(1)</script>"
            "<h1>Title</h1><p>Hello World</p>"
            "<nav>Nav</nav><footer>Footer</footer>"
            "</body></html>"
        )
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        async def fake_to_thread(fn, *args, **kwargs):
            return mock_response

        with (
            patch("backend.plugins.web_search.client.asyncio.to_thread", side_effect=fake_to_thread),
            patch("backend.plugins.web_search.client.async_validate_url_ssrf", new_callable=AsyncMock),
        ):
            text = await client.scrape("https://example.com/page")

        # script, style, nav, footer should be stripped
        assert "alert" not in text
        assert "color:red" not in text
        assert "Nav" not in text
        assert "Footer" not in text
        # Meaningful content should remain
        assert "Title" in text
        assert "Hello World" in text
        await client.close()

    @pytest.mark.asyncio
    async def test_scrape_truncation(self):
        """scrape() truncates content to _MAX_SCRAPE_CHARS (50 000)."""
        from backend.plugins.web_search.client import _MAX_SCRAPE_CHARS

        client = self._make_client()

        # Build HTML with very long text
        long_text = "A" * (_MAX_SCRAPE_CHARS + 5000)
        html = f"<html><body><p>{long_text}</p></body></html>"
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        async def fake_to_thread(fn, *args, **kwargs):
            return mock_response

        with (
            patch("backend.plugins.web_search.client.asyncio.to_thread", side_effect=fake_to_thread),
            patch("backend.plugins.web_search.client.async_validate_url_ssrf", new_callable=AsyncMock),
        ):
            text = await client.scrape("https://example.com/big")

        assert len(text) <= _MAX_SCRAPE_CHARS
        await client.close()

    @pytest.mark.asyncio
    async def test_scrape_ssrf_validation_called(self):
        """scrape() calls async_validate_url_ssrf before making the request."""
        client = self._make_client()

        with patch(
            "backend.plugins.web_search.client.async_validate_url_ssrf",
            new_callable=AsyncMock,
            side_effect=ValueError("resolves to private address"),
        ):
            with pytest.raises(ValueError, match="private address"):
                await client.scrape("http://192.168.1.1/admin")

        await client.close()

    @pytest.mark.asyncio
    async def test_scrape_http_error_propagated(self):
        """Non-2xx responses raise httpx.HTTPStatusError."""
        import httpx

        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return mock_response

        with (
            patch("backend.plugins.web_search.client.asyncio.to_thread", side_effect=fake_to_thread),
            patch("backend.plugins.web_search.client.async_validate_url_ssrf", new_callable=AsyncMock),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.scrape("https://example.com/404")

        await client.close()

    def test_cache_key_deterministic(self):
        """Same inputs produce the same cache key."""
        client = self._make_client()
        key1 = client._cache_key("hello", 5)
        key2 = client._cache_key("hello", 5)
        assert key1 == key2

    def test_cache_key_case_insensitive(self):
        """Cache key normalises the query to lowercase."""
        client = self._make_client()
        key1 = client._cache_key("Hello World", 5)
        key2 = client._cache_key("hello world", 5)
        assert key1 == key2

    def test_cache_key_different_max_results(self):
        """Different max_results produce different cache keys."""
        client = self._make_client()
        key1 = client._cache_key("test", 5)
        key2 = client._cache_key("test", 10)
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_metasearch_sync_static(self):
        """_metasearch_sync extracts title/href/body from DDGS results."""
        from backend.plugins.web_search.client import WebSearchClient

        raw_results = [
            {"title": "T1", "href": "https://a.com", "body": "B1", "extra": "ignored"},
            {"title": "T2", "href": "https://b.com", "body": "B2"},
        ]
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = raw_results

        with patch("backend.plugins.web_search.client.DDGS", return_value=mock_ddgs_instance):
            results = WebSearchClient._metasearch_sync("test query", 2, "it-it")

        assert len(results) == 2
        assert results[0] == {"title": "T1", "href": "https://a.com", "body": "B1"}
        assert results[1] == {"title": "T2", "href": "https://b.com", "body": "B2"}
        mock_ddgs_instance.text.assert_called_once_with("test query", region="it-it", max_results=2, backend="auto")
