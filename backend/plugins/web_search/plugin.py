"""AL\\CE — Web Search plugin.

Exposes ``web_search`` and ``web_scrape`` tools powered by DDGS metasearch
and httpx-based page scraping.  All external requests go through SSRF
validation; search calls are rate-limited and cached.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.web_search.client import WebSearchClient, _DDGS_AVAILABLE

if TYPE_CHECKING:
    from backend.core.context import AppContext


class WebSearchPlugin(BasePlugin):
    """Web search and page scraping via DDGS metasearch."""

    plugin_name: str = "web_search"
    plugin_version: str = "1.0.0"
    plugin_description: str = "Web search and page scraping via DDGS metasearch."
    plugin_dependencies: list[str] = []
    plugin_priority: int = 40

    def __init__(self) -> None:
        super().__init__()
        self._client: WebSearchClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Create the search client from configuration.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)

        cfg = ctx.config.web_search
        self._client = WebSearchClient(
            max_results=cfg.max_results,
            cache_ttl_s=cfg.cache_ttl_s,
            request_timeout_s=cfg.request_timeout_s,
            rate_limit_s=cfg.rate_limit_s,
            region=cfg.region,
            proxy_http=cfg.proxy_http,
            proxy_https=cfg.proxy_https,
        )

        if not _DDGS_AVAILABLE:
            logger.warning(
                "web_search plugin: ddgs is not installed"
                " — search tool will be unavailable"
            )

    async def cleanup(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        await super().cleanup()

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for web search and scrape.

        Returns:
            A list of two ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="web_search",
                description=(
                    "Search the web using multiple engines (Google, Bing, DuckDuckGo, "
                    "Brave, Yahoo, etc.). Returns a list of results with title, URL and snippet. "
                    "IMPORTANT: snippets may contain outdated prices from old news articles — "
                    "always check the article date before citing a price. "
                    "For real-time prices use web_scrape on a price-comparison page "
                    "(e.g. trovaprezzi.it, kelkoo.it, idealo.it) found in the results."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": (
                                "Number of results to return (1–20). "
                                "Defaults to 5."
                            ),
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                    },
                    "required": ["query"],
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="web_scrape",
                description=(
                    "Fetch a web page and return its text content. "
                    "Use this to get real-time prices and direct product links from "
                    "e-commerce or price-comparison sites (trovaprezzi.it, idealo.it, "
                    "amazon.it, etc.) after a web_search identifies candidate URLs. "
                    "Also useful for reading articles or documentation. "
                    "PREFER mcp_primp_fetch over this tool for sites returning 403/CAPTCHA/timeout."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL of the page to scrape.",
                        },
                    },
                    "required": ["url"],
                },
                result_type="string",
                risk_level="medium",
                timeout_ms=15_000,
                max_result_chars=20_000,
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
            tool_name: ``"web_search"`` or ``"web_scrape"``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the payload or an error.
        """
        if self._client is None:
            return ToolResult.error("Web search plugin not initialized")

        start = time.perf_counter()

        if tool_name == "web_search":
            return await self._handle_search(args, start)
        if tool_name == "web_scrape":
            return await self._handle_scrape(args, start)

        return ToolResult.error(f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------
    # Dependency / health
    # ------------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list with ``"ddgs"`` if missing, else empty.
        """
        if not _DDGS_AVAILABLE:
            return ["ddgs"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if DDGS library is available, ERROR otherwise.

        Returns:
            Current connection status.
        """
        if _DDGS_AVAILABLE:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    async def _handle_search(
        self,
        args: dict[str, Any],
        start: float,
    ) -> ToolResult:
        """Execute a web search.

        Args:
            args: Must contain ``query``; may contain ``max_results``.
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` with JSON results or error.
        """
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.error("Missing required parameter: query")

        max_results = args.get("max_results", 5)
        if not isinstance(max_results, int) or not 1 <= max_results <= 20:
            max_results = 5

        try:
            results = await self._client.search(query, max_results)
        except RuntimeError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            logger.error("web_search failed: {}", exc)
            return ToolResult.error(f"Search failed: {exc}")

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={"query": query, "results": results},
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _handle_scrape(
        self,
        args: dict[str, Any],
        start: float,
    ) -> ToolResult:
        """Fetch and extract text from a web page.

        Args:
            args: Must contain ``url``.
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` with the page text or error.
        """
        url = (args.get("url") or "").strip()
        if not url:
            return ToolResult.error("Missing required parameter: url")

        try:
            text = await self._client.scrape(url)
        except ValueError as exc:
            # SSRF validation failure
            return ToolResult.error(f"URL blocked: {exc}")
        except RuntimeError as exc:
            # Domain blocked / anti-bot — give LLM actionable advice
            logger.warning("web_scrape blocked for {}: {}", url, exc)
            return ToolResult.error(
                f"{exc} — Do NOT retry this domain. "
                f"Use web_search results directly or try a different URL."
            )
        except Exception as exc:
            logger.error("web_scrape failed for {}: {}", url, exc)
            return ToolResult.error(
                f"Scrape failed: {exc} — Try a different URL."
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content=text,
            content_type="text/plain",
            execution_time_ms=elapsed_ms,
        )
