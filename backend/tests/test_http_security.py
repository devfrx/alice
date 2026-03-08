"""Tests for HTTP security SSRF-prevention utilities."""

from __future__ import annotations

import socket

import pytest
from unittest.mock import patch

from backend.core.http_security import (
    async_validate_url_ssrf,
    create_ssrf_safe_event_hooks,
    create_ssrf_safe_event_hooks_sync,
    validate_url_ssrf,
)

# Fake DNS result that resolves to a public IP
_PUBLIC_ADDRINFO = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
]

# Fake DNS result that resolves to a private/loopback IP
_PRIVATE_ADDRINFO = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
]

# Fake DNS result that resolves to an IPv4-mapped IPv6 loopback
_IPV4_MAPPED_V6_ADDRINFO = [
    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", 0, 0, 0)),
]


# ===================================================================
# TestValidateUrlSsrf
# ===================================================================


class TestValidateUrlSsrf:
    """Validate SSRF prevention on synchronous helper."""

    # --- valid URLs pass ------------------------------------------------

    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    def test_valid_http_url_passes(self, _mock_dns) -> None:
        validate_url_ssrf("http://example.com/path?q=1")

    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    def test_valid_https_url_passes(self, _mock_dns) -> None:
        validate_url_ssrf("https://example.com/secure")

    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    def test_public_ip_literal_passes(self, _mock_dns) -> None:
        validate_url_ssrf("http://93.184.216.34/resource")

    # --- UNC path -------------------------------------------------------

    def test_unc_path_blocked(self) -> None:
        with pytest.raises(ValueError, match="UNC"):
            validate_url_ssrf("\\\\server\\share")

    # --- scheme checks --------------------------------------------------

    def test_file_scheme_blocked(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_url_ssrf("file:///etc/passwd")

    def test_ftp_scheme_blocked(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_url_ssrf("ftp://ftp.example.com/file")

    def test_ssh_scheme_blocked(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_url_ssrf("ssh://git@github.com/repo")

    def test_no_scheme_blocked(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_url_ssrf("example.com/path")

    # --- blocked hostnames ----------------------------------------------

    def test_localhost_blocked(self) -> None:
        with pytest.raises(ValueError, match="blocked"):
            validate_url_ssrf("http://localhost/admin")

    def test_localhost_localdomain_blocked(self) -> None:
        with pytest.raises(ValueError, match="blocked"):
            validate_url_ssrf("http://localhost.localdomain/admin")

    def test_ip6_localhost_blocked(self) -> None:
        with pytest.raises(ValueError, match="blocked"):
            validate_url_ssrf("http://ip6-localhost/admin")

    # --- private IP literals --------------------------------------------

    def test_127_0_0_1_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://127.0.0.1/admin")

    def test_10_x_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://10.0.0.1/internal")

    def test_172_16_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://172.16.0.1/internal")

    def test_192_168_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://192.168.1.1/router")

    def test_169_254_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://169.254.169.254/metadata")

    def test_ipv6_loopback_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://[::1]/admin")

    def test_ipv6_private_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://[fc00::1]/internal")

    def test_ipv6_link_local_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://[fe80::1]/internal")

    # --- DNS-based blocking ---------------------------------------------

    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PRIVATE_ADDRINFO)
    def test_dns_resolves_to_private_blocked(self, _mock_dns) -> None:
        with pytest.raises(ValueError, match="private address"):
            validate_url_ssrf("http://evil.example.com/steal")

    @patch(
        "backend.core.http_security.socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    )
    def test_dns_failure_raises(self, _mock_dns) -> None:
        with pytest.raises(ValueError, match="DNS resolution failed"):
            validate_url_ssrf("http://nonexistent.invalid/path")

    # --- empty hostname -------------------------------------------------

    def test_empty_hostname_blocked(self) -> None:
        with pytest.raises(ValueError, match="no hostname"):
            validate_url_ssrf("http:///path")


# ===================================================================
# TestAsyncValidateUrlSsrf
# ===================================================================


class TestAsyncValidateUrlSsrf:
    """Validate the async wrapper delegates correctly."""

    @pytest.mark.asyncio
    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    async def test_valid_url_passes(self, _mock_dns) -> None:
        await async_validate_url_ssrf("https://example.com/ok")

    @pytest.mark.asyncio
    async def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError):
            await async_validate_url_ssrf("ftp://evil.example.com")

    @pytest.mark.asyncio
    @patch("backend.core.http_security.asyncio.to_thread", wraps=__import__("asyncio").to_thread)
    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    async def test_uses_asyncio_to_thread(self, _mock_dns, mock_to_thread) -> None:
        await async_validate_url_ssrf("https://example.com")
        mock_to_thread.assert_awaited_once()


# ===================================================================
# TestIPv4MappedIPv6Bypass
# ===================================================================


class TestIPv4MappedIPv6Bypass:
    """Ensure IPv4-mapped IPv6 addresses cannot bypass SSRF checks."""

    def test_ipv4_mapped_loopback_literal_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://[::ffff:127.0.0.1]/admin")

    def test_ipv4_mapped_private_10_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://[::ffff:10.0.0.1]/internal")

    def test_ipv4_mapped_private_192_168_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://[::ffff:192.168.1.1]/router")

    @patch(
        "backend.core.http_security.socket.getaddrinfo",
        return_value=_IPV4_MAPPED_V6_ADDRINFO,
    )
    def test_dns_resolves_to_ipv4_mapped_v6_blocked(self, _mock_dns) -> None:
        with pytest.raises(ValueError, match="private address"):
            validate_url_ssrf("http://sneaky.example.com/steal")


# ===================================================================
# TestAdditionalBlockedRanges
# ===================================================================


class TestAdditionalBlockedRanges:
    """Ensure newly added private/reserved network ranges are blocked."""

    def test_current_network_0_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://0.0.0.1/")

    def test_carrier_grade_nat_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://100.64.0.1/")

    def test_benchmark_testing_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://198.18.0.1/")

    def test_ietf_protocol_assignments_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://192.0.0.1/")

    def test_documentation_test_net_1_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://192.0.2.1/")

    def test_documentation_test_net_2_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://198.51.100.1/")

    def test_documentation_test_net_3_blocked(self) -> None:
        with pytest.raises(ValueError, match="private range"):
            validate_url_ssrf("http://203.0.113.1/")


# ===================================================================
# TestSSRFSafeEventHooks
# ===================================================================


class TestSSRFSafeEventHooks:
    """Validate the redirect-checking event hook helpers."""

    def test_create_ssrf_safe_event_hooks_returns_dict_with_response_key(self) -> None:
        hooks = create_ssrf_safe_event_hooks()
        assert "response" in hooks
        assert len(hooks["response"]) == 1
        assert callable(hooks["response"][0])

    def test_create_ssrf_safe_event_hooks_sync_returns_dict(self) -> None:
        hooks = create_ssrf_safe_event_hooks_sync()
        assert "response" in hooks
        assert len(hooks["response"]) == 1
        assert callable(hooks["response"][0])

    @pytest.mark.asyncio
    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    async def test_async_hook_allows_safe_redirect(self, _mock_dns) -> None:
        import httpx

        hooks = create_ssrf_safe_event_hooks()
        hook_fn = hooks["response"][0]

        mock_response = httpx.Response(
            status_code=302,
            headers={"location": "https://safe.example.com/page"},
            request=httpx.Request("GET", "https://example.com/start"),
        )
        # Should not raise
        await hook_fn(mock_response)

    @pytest.mark.asyncio
    async def test_async_hook_blocks_private_redirect(self) -> None:
        import httpx

        hooks = create_ssrf_safe_event_hooks()
        hook_fn = hooks["response"][0]

        mock_response = httpx.Response(
            status_code=302,
            headers={"location": "http://127.0.0.1/secret"},
            request=httpx.Request("GET", "https://example.com/start"),
        )
        with pytest.raises(ValueError):
            await hook_fn(mock_response)

    @patch("backend.core.http_security.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO)
    def test_sync_hook_allows_safe_redirect(self, _mock_dns) -> None:
        import httpx

        hooks = create_ssrf_safe_event_hooks_sync()
        hook_fn = hooks["response"][0]

        mock_response = httpx.Response(
            status_code=302,
            headers={"location": "https://safe.example.com/page"},
            request=httpx.Request("GET", "https://example.com/start"),
        )
        hook_fn(mock_response)

    def test_sync_hook_blocks_private_redirect(self) -> None:
        import httpx

        hooks = create_ssrf_safe_event_hooks_sync()
        hook_fn = hooks["response"][0]

        mock_response = httpx.Response(
            status_code=302,
            headers={"location": "http://10.0.0.1/internal"},
            request=httpx.Request("GET", "https://example.com/start"),
        )
        with pytest.raises(ValueError):
            hook_fn(mock_response)
