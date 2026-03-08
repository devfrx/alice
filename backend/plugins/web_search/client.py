"""O.M.N.I.A. — Web search client.

Wraps DuckDuckGo search (sync, run via ``asyncio.to_thread``) and
``httpx``-based page scraping with SSRF protection, rate limiting,
and in-memory result caching.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.core.http_security import (
    async_validate_url_ssrf,
    create_ssrf_safe_event_hooks,
)

# -- Lazy DDG import -------------------------------------------------------

try:
    from duckduckgo_search import DDGS

    _DDG_AVAILABLE = True
except ImportError:
    DDGS = None  # type: ignore[assignment,misc]
    _DDG_AVAILABLE = False


# -- Constants --------------------------------------------------------------

_MAX_SCRAPE_CHARS = 50_000
"""Maximum characters kept from a scraped page."""

_MAX_CACHE_SIZE = 200
"""Maximum number of entries in the search result cache (FIFO eviction)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class WebSearchClient:
    """Async-friendly web search + scrape client.

    Args:
        max_results: Default number of search results.
        cache_ttl_s: Seconds before cached results expire.
        request_timeout_s: HTTP request timeout in seconds.
        rate_limit_s: Minimum seconds between DDG search calls.
        region: DuckDuckGo region code (e.g. 'it-it').
        proxy_http: Optional HTTP proxy URL.
        proxy_https: Optional HTTPS proxy URL.
    """

    def __init__(
        self,
        *,
        max_results: int = 5,
        cache_ttl_s: int = 300,
        request_timeout_s: int = 10,
        rate_limit_s: float = 2.0,
        region: str = "it-it",
        proxy_http: str | None = None,
        proxy_https: str | None = None,
    ) -> None:
        self._max_results = max_results
        self._cache_ttl_s = cache_ttl_s
        self._request_timeout_s = request_timeout_s
        self._rate_limit_s = rate_limit_s
        self._region = region

        # Build proxy URL (httpx 0.28+ uses singular 'proxy' param)
        self._proxy_url = proxy_https or proxy_http or None

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(request_timeout_s, connect=5.0),
            follow_redirects=True,
            proxy=self._proxy_url,
            headers={"User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )},
            event_hooks=create_ssrf_safe_event_hooks(),
        )

        # Rate limiting state
        self._rate_lock = asyncio.Lock()
        self._last_search_ts: float = 0.0

        # In-memory cache: {query_hash: (timestamp, results)}
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run a DuckDuckGo text search.

        Args:
            query: Search query string.
            max_results: Override default max results (1–20).

        Returns:
            A list of result dicts with keys ``title``, ``href``, ``body``.

        Raises:
            RuntimeError: If the ``duckduckgo-search`` package is missing.
        """
        if not _DDG_AVAILABLE:
            raise RuntimeError(
                "duckduckgo-search is not installed — "
                "run: uv add duckduckgo-search"
            )

        effective_max = max_results or self._max_results

        # Check cache
        cache_key = self._cache_key(query, effective_max)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for query={!r}", query)
            return cached

        # Rate limiting
        await self._enforce_rate_limit()

        # DDG is synchronous — run in a thread
        results = await asyncio.to_thread(
            self._ddg_search_sync,
            query,
            effective_max,
            self._region,
            self._proxy_url,
        )

        # Evict oldest entry if cache is full (FIFO)
        if len(self._cache) >= _MAX_CACHE_SIZE:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        # Store in cache
        self._cache[cache_key] = (time.monotonic(), results)
        return results

    # ------------------------------------------------------------------
    # Scrape
    # ------------------------------------------------------------------

    async def scrape(self, url: str) -> str:
        """Fetch a web page and return its text content.

        SSRF validation is performed before making the request.

        Args:
            url: The URL to scrape.

        Returns:
            Plain-text content truncated to 50 000 characters.

        Raises:
            ValueError: If the URL fails SSRF validation.
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        await async_validate_url_ssrf(url)

        response = await self._http.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script/style elements for cleaner text
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        return text[:_MAX_SCRAPE_CHARS]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ddg_search_sync(
        query: str,
        max_results: int,
        region: str,
        proxy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronous DDG search (called via ``to_thread``)."""
        ddg = DDGS(proxy=proxy) if proxy else DDGS()
        raw = ddg.text(query, region=region, max_results=max_results)
        results = [
            {"title": r.get("title", ""), "href": r.get("href", ""), "body": r.get("body", "")}
            for r in raw
        ]
        if not results:
            logger.warning("DDG returned no results for query={!r}", query)
        return results

    async def _enforce_rate_limit(self) -> None:
        """Wait until at least ``rate_limit_s`` seconds since last search."""
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_search_ts
            if elapsed < self._rate_limit_s:
                wait = self._rate_limit_s - elapsed
                logger.debug("Rate limit: waiting {:.1f}s", wait)
                await asyncio.sleep(wait)
            self._last_search_ts = time.monotonic()

    def _cache_key(self, query: str, max_results: int) -> str:
        """Produce a deterministic cache key."""
        raw = f"{query.strip().lower()}|{max_results}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, key: str) -> list[dict[str, Any]] | None:
        """Return cached results if still valid, else ``None``."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, results = entry
        if (time.monotonic() - ts) > self._cache_ttl_s:
            del self._cache[key]
            return None
        return results
