"""O.M.N.I.A. — RSS/Atom feed reader with caching.

Fetches and normalises RSS/Atom feeds using ``feedparser``, with
SSRF validation on every outbound request and an in-memory TTL cache.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger

from backend.core.http_security import validate_url_ssrf

# -- Lazy import of feedparser ---------------------------------------------

try:
    import feedparser

    _FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None  # type: ignore[assignment]
    _FEEDPARSER_AVAILABLE = False


class FeedReader:
    """Async RSS/Atom reader with per-URL TTL cache.

    Args:
        cache_ttl_minutes: How many minutes cached entries remain valid.
    """

    _MAX_CACHE_SIZE: int = 100

    def __init__(self, cache_ttl_minutes: int = 15) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            headers={"User-Agent": "OMNIA-NewsReader/1.0"},
        )
        self._cache_ttl_s = cache_ttl_minutes * 60
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._logger = logger.bind(component="FeedReader")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_feed(
        self,
        url: str,
        max_articles: int = 10,
        timeout_s: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch and normalise a single RSS/Atom feed.

        Args:
            url: Feed URL (validated against SSRF before fetching).
            max_articles: Maximum number of entries to return.
            timeout_s: HTTP request timeout in seconds.

        Returns:
            A list of normalised article dicts.

        Raises:
            ValueError: If the URL fails SSRF validation.
            RuntimeError: If ``feedparser`` is not installed.
        """
        if not _FEEDPARSER_AVAILABLE:
            raise RuntimeError("feedparser is not installed")

        # SSRF check (sync, but fast — no DNS for obvious cases)
        await asyncio.to_thread(validate_url_ssrf, url)

        # Cache hit?
        cached = self._cache.get(url)
        if cached is not None:
            ts, articles = cached
            if (time.monotonic() - ts) < self._cache_ttl_s:
                self._logger.debug("Cache hit for {}", url)
                return articles[:max_articles]

        # Fetch
        response = await self._client.get(url, timeout=timeout_s)
        response.raise_for_status()

        # feedparser is CPU-bound → offload to thread
        parsed = await asyncio.to_thread(feedparser.parse, response.text)

        articles = [
            self._normalise_entry(entry, url)
            for entry in (parsed.entries or [])
        ]

        # Evict oldest entry if cache is at capacity
        if len(self._cache) >= self._MAX_CACHE_SIZE and url not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        # Update cache (store all, slice on read)
        self._cache[url] = (time.monotonic(), articles)

        return articles[:max_articles]

    async def fetch_all_feeds(
        self,
        urls: list[str],
        max_per_feed: int = 10,
        timeout_s: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch multiple feeds concurrently and merge results.

        Args:
            urls: List of feed URLs.
            max_per_feed: Maximum articles per feed.
            timeout_s: Per-request timeout in seconds.

        Returns:
            Flat list of normalised articles from all successful feeds.
        """
        results = await asyncio.gather(
            *[
                self.fetch_feed(url, max_per_feed, timeout_s)
                for url in urls
            ],
            return_exceptions=True,
        )

        articles: list[dict[str, Any]] = []
        for idx, result in enumerate(results):
            if isinstance(result, BaseException):
                self._logger.warning(
                    "Feed {} failed: {}", urls[idx], result,
                )
                continue
            articles.extend(result)

        return articles

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_entry(
        entry: Any,
        source_url: str,
    ) -> dict[str, Any]:
        """Extract a consistent dict from a feedparser entry.

        Args:
            entry: A single ``feedparser.FeedParserDict`` entry.
            source_url: The feed URL (for provenance).

        Returns:
            Normalised article dict with title, summary, link,
            published_iso and source.
        """
        published = getattr(entry, "published", "") or ""
        return {
            "title": getattr(entry, "title", "") or "",
            "summary": (getattr(entry, "summary", "") or "")[:500],
            "link": getattr(entry, "link", "") or "",
            "published_iso": published,
            "source": source_url,
        }
