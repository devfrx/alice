"""O.M.N.I.A. — Web search client.

Wraps DDGS metasearch (sync, run via ``asyncio.to_thread``) and
``primp``-based page scraping with SSRF protection, rate limiting,
and in-memory result caching.

Uses ``primp.Client`` for scraping because it impersonates real browser
TLS fingerprints, which avoids the 403 / empty-response blocks that
plain ``httpx`` triggers on sites like trovaprezzi.it and idealo.it.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from primp import Client as PrimpClient

from backend.core.http_security import (
    async_validate_url_ssrf,
    create_ssrf_safe_event_hooks,
)

# -- Lazy DDGS import ------------------------------------------------------

try:
    from ddgs import DDGS

    _DDGS_AVAILABLE = True
except ImportError:
    DDGS = None  # type: ignore[assignment,misc]
    _DDGS_AVAILABLE = False


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
        rate_limit_s: Minimum seconds between search calls.
        region: Search region code (e.g. 'it-it').
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

        # primp client for scraping — impersonates a real browser TLS
        # fingerprint, which bypasses 403s on anti-bot sites.
        self._primp = PrimpClient(
            impersonate="firefox",
            follow_redirects=False,
            timeout=request_timeout_s,
        )

        # Rate limiting state
        self._rate_lock = asyncio.Lock()
        self._last_search_ts: float = 0.0

        # In-memory cache: {query_hash: (timestamp, results)}
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

        # Track failed scrape URLs to avoid retrying the same domain
        self._scrape_failures: dict[str, float] = {}
        self._failure_cooldown_s: float = 300.0  # 5 minutes

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run a metasearch query.

        Args:
            query: Search query string.
            max_results: Override default max results (1–20).

        Returns:
            A list of result dicts with keys ``title``, ``href``, ``body``.

        Raises:
            RuntimeError: If the ``ddgs`` package is missing.
        """
        if not _DDGS_AVAILABLE:
            raise RuntimeError(
                "ddgs is not installed — "
                "run: uv add ddgs"
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

        # DDGS is synchronous — run in a thread
        results = await asyncio.to_thread(
            self._metasearch_sync,
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
        Uses ``primp`` for browser-like TLS impersonation to avoid 403s.

        Args:
            url: The URL to scrape.

        Returns:
            Plain-text content truncated to 50 000 characters.

        Raises:
            ValueError: If the URL fails SSRF validation.
            RuntimeError: If the domain was recently blocked (403/timeout).
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        await async_validate_url_ssrf(url)

        # Check if this domain recently failed — avoid retry spirals
        domain = urlparse(url).netloc
        fail_ts = self._scrape_failures.get(domain)
        if fail_ts and (time.monotonic() - fail_ts) < self._failure_cooldown_s:
            raise RuntimeError(
                f"Domain '{domain}' is temporarily blocked "
                f"(failed recently). Try a different site."
            )

        # Use primp (browser TLS fingerprint) in a thread
        response = await asyncio.to_thread(self._primp.get, url)

        # Handle redirects manually with SSRF validation
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if location:
                resolved = urljoin(url, location)
                await async_validate_url_ssrf(resolved)
                response = await asyncio.to_thread(
                    self._primp.get, resolved,
                )

        if response.status_code in (403, 429, 503):
            self._scrape_failures[domain] = time.monotonic()
            raise RuntimeError(
                f"HTTP {response.status_code} from '{domain}' — "
                f"site blocks automated access. Try a different site."
            )
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
    def _metasearch_sync(
        query: str,
        max_results: int,
        region: str,
        proxy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronous DDGS metasearch (called via ``to_thread``)."""
        ddgs = DDGS(proxy=proxy) if proxy else DDGS()
        raw = ddgs.text(query, region=region, max_results=max_results, backend="auto")
        results = [
            {"title": r.get("title", ""), "href": r.get("href", ""), "body": r.get("body", "")}
            for r in raw
        ]
        if not results:
            logger.warning("DDGS returned no results for query={!r}", query)
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
