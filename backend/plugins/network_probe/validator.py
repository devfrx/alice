"""AL\\CE — network_probe: Local network address validator.

Ensures all probe targets are RFC‑1918 / loopback only — the inverse
of the SSRF guard in ``backend.core.http_security``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Final

from loguru import logger

__all__ = [
    "LocalNetworkValidationError",
    "validate_host_local",
    "async_validate_host_local",
]

# -- Constants -------------------------------------------------------------

_MAX_HOST_LEN: Final[int] = 253

_LOCAL_NETWORKS: tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network, ...
] = (
    # IPv4
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC-1918 Class A
    ipaddress.ip_network("172.16.0.0/12"),      # RFC-1918 Class B
    ipaddress.ip_network("192.168.0.0/16"),     # RFC-1918 Class C
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local
    # IPv6
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-local
)


# -- Helpers ---------------------------------------------------------------


def _is_local_ip(addr: str) -> bool:
    """Return ``True`` if *addr* belongs to a local / loopback range.

    IPv4-mapped IPv6 addresses (e.g. ``::ffff:192.168.1.1``) are
    unwrapped to their IPv4 equivalent before checking.

    Args:
        addr: IP address string to check.

    Returns:
        ``True`` when the address falls inside any ``_LOCAL_NETWORKS``.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # Unwrap IPv4-mapped IPv6 to prevent bypass
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _LOCAL_NETWORKS)


# -- Exceptions -----------------------------------------------------------


class LocalNetworkValidationError(ValueError):
    """Raised when a host resolves to a non-local (public) address."""


# -- Public API ------------------------------------------------------------


def validate_host_local(host: str) -> None:
    """Validate that *host* resolves exclusively to local addresses.

    Checks performed (in order):

    1. Host length (max 253 characters).
    2. Direct IP-literal fast path — skip DNS if the host is an IP.
    3. DNS resolution — **all** addresses must be local.

    Args:
        host: Hostname or IP literal to validate.

    Raises:
        LocalNetworkValidationError: If the host is too long, resolves
            to a public address, or DNS resolution fails.
    """
    if not host or len(host) > _MAX_HOST_LEN:
        raise LocalNetworkValidationError(
            f"Invalid host (empty or exceeds {_MAX_HOST_LEN} chars): {host!r}"
        )

    # Fast path: direct IP literal — no DNS needed
    if _is_local_ip(host):
        return

    # If it *looks* like an IP but isn't local, reject immediately
    try:
        ipaddress.ip_address(host)
        # If we reach here, the host IS a valid IP but NOT local
        logger.warning("network_probe blocked: {} is not a local IP", host)
        raise LocalNetworkValidationError(
            f"IP address '{host}' is not in a local/private range"
        )
    except ValueError:
        pass  # Not an IP literal — proceed with DNS resolution

    # DNS resolution: every resolved address must be local
    try:
        results = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise LocalNetworkValidationError(
            f"DNS resolution failed for '{host}': {exc}"
        ) from exc

    for _family, _type, _proto, _canon, sockaddr in results:
        ip_str = sockaddr[0]
        # Unwrap IPv4-mapped IPv6 for logging clarity
        try:
            resolved = ipaddress.ip_address(ip_str)
            if isinstance(resolved, ipaddress.IPv6Address) and resolved.ipv4_mapped:
                ip_str = str(resolved.ipv4_mapped)
        except ValueError:
            pass

        if not _is_local_ip(ip_str):
            logger.warning(
                "network_probe blocked: {} resolved to public IP {}", host, ip_str
            )
            raise LocalNetworkValidationError(
                f"Hostname '{host}' resolves to non-local address {ip_str}"
            )


async def async_validate_host_local(host: str) -> None:
    """Async wrapper around :func:`validate_host_local`.

    DNS resolution is offloaded to a thread via ``asyncio.to_thread``
    so the event loop is never blocked.

    Args:
        host: Hostname or IP literal to validate.

    Raises:
        LocalNetworkValidationError: If the host resolves to a
            non-local address.
    """
    await asyncio.to_thread(validate_host_local, host)
