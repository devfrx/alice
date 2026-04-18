"""mcp-fetch-primp — MCP stdio server with browser-grade TLS impersonation.

Drop-in replacement for ``mcp-server-fetch`` that uses ``primp`` instead of
plain ``httpx``.  Primp impersonates real browser TLS fingerprints, which
bypasses Cloudflare, Radware, and most other anti-bot systems that reject the
standard Python TLS stack.

Interface is identical to ``mcp-server-fetch``:
  - Tool ``fetch`` with params: url, max_length, start_index, raw
  - robots.txt is always ignored (no autonomous / user-agent distinction)

Run via the backend venv::

    backend/.venv/Scripts/python.exe backend/tools/mcp_fetch_primp.py
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import sys
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from primp import Client as PrimpClient

# ---------------------------------------------------------------------------
# SSRF protection (mirrors backend/core/http_security.py — inlined so this
# script stays self-contained and runnable outside the backend package)
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}

_ALLOWED_SCHEMES = {"http", "https"}


def _is_private_ip(addr: str) -> bool:
    """Return True if *addr* is a private / loopback / link-local address."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # Unwrap IPv4-mapped IPv6 to prevent bypass via ::ffff:127.0.0.1
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _PRIVATE_NETWORKS)


def _validate_url_sync(url: str) -> None:
    """Raise ValueError if *url* targets a private / local network or uses a blocked scheme.

    Performs a **blocking** DNS lookup; prefer :func:`_validate_url` from
    async code so the event loop is not stalled.
    """
    if url.startswith("\\\\"):
        raise ValueError("UNC paths are not allowed")

    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(f"Scheme '{parsed.scheme}' is not allowed; only {_ALLOWED_SCHEMES}")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL has no hostname")

    if hostname in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Hostname '{hostname}' is blocked")

    # Reject IP literals that are obviously private (fast path, no DNS)
    if _is_private_ip(hostname):
        raise ValueError(f"IP '{hostname}' is in a private range")

    # DNS resolution check — reject private IPs obtained via DNS
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    for _family, _type, _proto, _canon, sockaddr in results:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            raise ValueError(f"'{hostname}' resolves to private address {ip_str}")


async def _validate_url(url: str) -> None:
    """Async wrapper around :func:`_validate_url_sync` that runs DNS in a thread.

    Keeps the event loop responsive when the resolver blocks.
    """
    await asyncio.to_thread(_validate_url_sync, url)


# ---------------------------------------------------------------------------
# HTML → text conversion
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "iframe", "aside"}


def _html_to_text(html: str) -> str:
    """Extract readable text from HTML using BeautifulSoup.

    Removes noise elements (nav, footer, scripts, etc.) then returns
    ``get_text()`` output — a reasonable plain-text / markdown-ish
    representation good enough for LLM consumption.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_BLOCK_TAGS):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

_DEFAULT_MAX_LENGTH = 20_000
_HARD_MAX_LENGTH = 200_000
"""Absolute upper bound on returned characters per call."""

_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
"""Drop responses larger than 10 MiB to bound memory use."""

_MAX_REDIRECTS = 5
"""Maximum number of redirects to follow (each re-validated for SSRF)."""

_TEXT_CONTENT_PREFIXES = ("text/", "application/xhtml", "application/xml", "application/json")

server = Server("mcp-fetch-primp")

# Single shared primp client (thread-safe for read operations).
# Uses "firefox" fingerprint — same as web_search/client.py web_scrape.
# Redirects are disabled here so we can re-validate the next hop against
# the SSRF allow-list (otherwise an attacker-controlled host could 302 to
# 169.254.169.254 or another internal address).
_primp = PrimpClient(
    impersonate="firefox",
    follow_redirects=False,
    timeout=30,
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch",
            description=(
                "Fetch a URL using real browser TLS fingerprint (Firefox via primp). "
                "Bypasses Cloudflare, Radware, and most anti-bot systems that block "
                "plain Python HTTP clients. Returns content as readable text. "
                "Use this instead of mcp-server-fetch for e-commerce, comparators, "
                "and any site returning 403 / CAPTCHA / timeout."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": (
                            f"Maximum characters to return (default {_DEFAULT_MAX_LENGTH}, "
                            f"max {_HARD_MAX_LENGTH})."
                        ),
                        "default": _DEFAULT_MAX_LENGTH,
                        "minimum": 1,
                        "maximum": _HARD_MAX_LENGTH,
                    },
                    "start_index": {
                        "type": "integer",
                        "description": "Start content from this character index (default 0).",
                        "default": 0,
                        "minimum": 0,
                    },
                    "raw": {
                        "type": "boolean",
                        "description": "Return raw HTML without conversion (default false)",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        )
    ]


def _clamp_int(value: object, default: int, *, low: int, high: int) -> int:
    """Coerce *value* to ``int`` and clamp it to ``[low, high]``.

    LLMs occasionally pass strings, floats, or wildly out-of-range values;
    this normalises them into a safe range without raising.
    """
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        ivalue = default
    return max(low, min(high, ivalue))


async def _fetch_with_redirect_validation(url: str) -> Any:
    """Issue ``GET url`` and follow up to ``_MAX_REDIRECTS`` redirects.

    Each redirect target is re-validated for SSRF before being requested,
    so a malicious server cannot trick the client into talking to an
    internal address by returning a 3xx response.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        await _validate_url(current)
        response = await asyncio.to_thread(_primp.get, current)
        status = getattr(response, "status_code", 0)
        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("location") if hasattr(response, "headers") else None
            if not location:
                return response
            current = urljoin(current, location)
            continue
        return response
    raise ValueError(f"Too many redirects (>{_MAX_REDIRECTS}) for '{url}'")


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "fetch":
        raise ValueError(f"Unknown tool: '{name}'")

    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("'url' is required and must be a non-empty string")

    max_length = _clamp_int(
        arguments.get("max_length", _DEFAULT_MAX_LENGTH),
        default=_DEFAULT_MAX_LENGTH,
        low=1,
        high=_HARD_MAX_LENGTH,
    )
    start_index = _clamp_int(
        arguments.get("start_index", 0),
        default=0,
        low=0,
        high=2_000_000,
    )
    raw = bool(arguments.get("raw", False))

    # SSRF check + redirect-aware fetch
    response = await _fetch_with_redirect_validation(url)
    response.raise_for_status()

    # Reject obviously non-textual responses (PDF, images, archives, …)
    content_type = ""
    if hasattr(response, "headers"):
        content_type = (response.headers.get("content-type") or "").lower()
    if content_type and not any(content_type.startswith(p) for p in _TEXT_CONTENT_PREFIXES):
        raise ValueError(
            f"Refusing to fetch non-text content-type '{content_type}'"
        )

    # Bound response size before decoding to text
    body_bytes = getattr(response, "content", None)
    if isinstance(body_bytes, (bytes, bytearray)) and len(body_bytes) > _MAX_RESPONSE_BYTES:
        raise ValueError(
            f"Response body too large ({len(body_bytes):,} bytes, max {_MAX_RESPONSE_BYTES:,})"
        )

    text = response.text
    content = text if raw else _html_to_text(text)

    if start_index >= len(content):
        return [TextContent(type="text", text="")]

    chunk = content[start_index : start_index + max_length]

    # Append pagination hint if content was truncated
    remaining = len(content) - (start_index + max_length)
    if remaining > 0:
        next_index = start_index + max_length
        chunk += (
            f"\n\n[Content truncated — {remaining} characters remaining. "
            f"Call fetch again with start_index={next_index} to continue.]"
        )

    return [TextContent(type="text", text=chunk)]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    # Ensure stdout is UTF-8 on Windows to avoid encoding timeouts
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    asyncio.run(_main())
