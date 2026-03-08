"""O.M.N.I.A. — HTTP security utilities for outbound request validation.

Shared SSRF-prevention module used by web_search, weather, news and any
plugin that makes outbound HTTP requests.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger

__all__ = [
    "validate_url_ssrf",
    "async_validate_url_ssrf",
    "create_ssrf_safe_event_hooks",
    "create_ssrf_safe_event_hooks_sync",
]

_ALLOWED_SCHEMES = {"http", "https"}

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
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}


def _is_private_ip(addr: str) -> bool:
    """Return True if *addr* belongs to a private / loopback / link-local range.

    IPv4-mapped IPv6 addresses (e.g. ``::ffff:127.0.0.1``) are unwrapped
    to their IPv4 equivalent before checking.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # Unwrap IPv4-mapped IPv6 addresses to prevent bypass
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _PRIVATE_NETWORKS)


def _resolve_and_check(hostname: str) -> None:
    """Resolve *hostname* via DNS and reject private/loopback addresses.

    This is a **sync** helper intended to be called inside
    ``asyncio.to_thread`` when an async context is needed.

    Raises:
        ValueError: If any resolved address is private or loopback.
    """
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    for family, _type, _proto, _canon, sockaddr in results:
        ip_str = sockaddr[0]
        # Unwrap IPv4-mapped IPv6 for logging clarity
        try:
            resolved = ipaddress.ip_address(ip_str)
            if isinstance(resolved, ipaddress.IPv6Address) and resolved.ipv4_mapped:
                ip_str = str(resolved.ipv4_mapped)
        except ValueError:
            pass
        if _is_private_ip(ip_str):
            logger.warning("SSRF blocked: {} resolved to private IP {}", hostname, ip_str)
            raise ValueError(
                f"Hostname '{hostname}' resolves to private address {ip_str}"
            )


def validate_url_ssrf(url: str) -> None:
    """Validate that *url* is safe for outbound HTTP requests.

    Checks performed (in order):
    1. Block UNC paths (``\\\\server\\share``).
    2. Enforce ``http`` / ``https`` scheme.
    3. Block well-known localhost hostnames.
    4. Resolve hostname and reject private IP ranges.

    Raises:
        ValueError: If the URL targets a private/local network or uses
            a blocked scheme.
    """
    if url.startswith("\\\\"):
        raise ValueError("UNC paths are not allowed")

    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Scheme '{parsed.scheme}' is not allowed; only {_ALLOWED_SCHEMES}"
        )

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL has no hostname")

    if hostname in _BLOCKED_HOSTNAMES:
        logger.warning("SSRF blocked: hostname '{}' is in blocklist", hostname)
        raise ValueError(f"Hostname '{hostname}' is blocked")

    # Direct IP-literal check (avoids DNS for obvious cases)
    if _is_private_ip(hostname):
        logger.warning("SSRF blocked: IP literal {} is private", hostname)
        raise ValueError(f"IP address '{hostname}' is in a private range")

    # DNS-based check — resolves hostname and verifies all addresses
    _resolve_and_check(hostname)


async def async_validate_url_ssrf(url: str) -> None:
    """Async wrapper around :func:`validate_url_ssrf`.

    DNS resolution is offloaded to a thread via ``asyncio.to_thread``
    so the event loop is never blocked.

    Raises:
        ValueError: If the URL targets a private/local network or uses
            a blocked scheme.
    """
    await asyncio.to_thread(validate_url_ssrf, url)


def create_ssrf_safe_event_hooks() -> dict:
    """Create httpx async event hooks that validate redirect URLs against SSRF.

    Usage::

        async with httpx.AsyncClient(event_hooks=create_ssrf_safe_event_hooks()) as client:
            resp = await client.get(url, follow_redirects=True)
    """
    import httpx  # noqa: local import to avoid hard dependency at module level

    async def _check_redirect(response: httpx.Response) -> None:
        if response.is_redirect:
            location = response.headers.get("location", "")
            if location:
                redirect_url = str(response.url.join(location))
                await async_validate_url_ssrf(redirect_url)

    return {"response": [_check_redirect]}


def create_ssrf_safe_event_hooks_sync() -> dict:
    """Create httpx sync event hooks that validate redirect URLs against SSRF.

    Usage::

        with httpx.Client(event_hooks=create_ssrf_safe_event_hooks_sync()) as client:
            resp = client.get(url, follow_redirects=True)
    """
    import httpx  # noqa: local import to avoid hard dependency at module level

    def _check_redirect(response: httpx.Response) -> None:
        if response.is_redirect:
            location = response.headers.get("location", "")
            if location:
                redirect_url = str(response.url.join(location))
                validate_url_ssrf(redirect_url)

    return {"response": [_check_redirect]}
