"""Tests for backend.services.email_service — EmailService + _LRUCache."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from backend.core.config import EmailConfig
from backend.core.event_bus import EventBus
from backend.services.email_service import EmailService, _LRUCache

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def email_config() -> EmailConfig:
    """Minimal EmailConfig with IMAP IDLE disabled."""
    return EmailConfig(
        enabled=True,
        imap_host="imap.example.com",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_ssl=False,
        username="user@example.com",
        password=SecretStr("test-password"),
        imap_idle_enabled=False,
        rate_limit_send_per_hour=3,
        max_email_body_chars=100,
        allowed_recipients=["allowed@example.com"],
    )


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def service(email_config: EmailConfig, event_bus: EventBus) -> EmailService:
    return EmailService(email_config, event_bus)


# ---------------------------------------------------------------------------
# _LRUCache tests
# ---------------------------------------------------------------------------


class TestLRUCache:
    """Unit tests for the in-memory TTL cache."""

    def test_set_and_get(self):
        cache = _LRUCache(max_size=10, ttl_s=300)
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_miss_returns_none(self):
        cache = _LRUCache(max_size=10, ttl_s=300)
        assert cache.get("nonexistent") is None

    def test_eviction_at_max_size(self):
        cache = _LRUCache(max_size=2, ttl_s=300)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # should evict oldest ("a")
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_invalidate(self):
        cache = _LRUCache(max_size=10, ttl_s=300)
        cache.set("x", 42)
        cache.invalidate("x")
        assert cache.get("x") is None

    def test_invalidate_missing_key_no_error(self):
        cache = _LRUCache(max_size=10, ttl_s=300)
        cache.invalidate("missing")  # should not raise

    def test_clear(self):
        cache = _LRUCache(max_size=10, ttl_s=300)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_ttl_expiry(self):
        cache = _LRUCache(max_size=10, ttl_s=1)
        cache.set("k", "v")
        # Manually backdate the entry timestamp
        key_val, _ = cache._store["k"]
        cache._store["k"] = (key_val, time.monotonic() - 2)
        assert cache.get("k") is None


# ---------------------------------------------------------------------------
# Password hydration (Task 5 — no more keyring lookup inside the service)
# ---------------------------------------------------------------------------


async def test_initialize_resolves_password_from_config(
    service: EmailService, email_config: EmailConfig,
):
    """Password arrives pre-hydrated on config.password (SecretStore-fed)."""
    with patch.object(service, "_connect_imap", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = MagicMock()
        await service.initialize()
    assert service._password_resolved == email_config.password.get_secret_value()
    assert service._password_resolved == "test-password"


# ---------------------------------------------------------------------------
# send — rate limit
# ---------------------------------------------------------------------------


async def test_send_rate_limit(service: EmailService):
    """ValueError when hourly send limit is exceeded."""
    # Pre-fill send log beyond the configured limit (3)
    now = time.monotonic()
    service._send_log = [now, now, now]

    with pytest.raises(ValueError, match="Limite invii orari"):
        await service.send(
            to=["allowed@example.com"],
            subject="Test",
            body="Test body",
        )


# ---------------------------------------------------------------------------
# send — whitelist
# ---------------------------------------------------------------------------


async def test_send_blocked_recipient(service: EmailService):
    """ValueError when sending to a recipient not in allowed_recipients."""
    with pytest.raises(ValueError, match="non nella whitelist"):
        await service.send(
            to=["blocked@evil.com"],
            subject="Test",
            body="body",
        )


async def test_send_allowed_recipient(
    email_config: EmailConfig,
    event_bus: EventBus,
):
    """Allowed recipient passes whitelist check and reaches SMTP send."""
    svc = EmailService(email_config, event_bus)
    svc._password_resolved = "test-password"

    with patch("backend.services.email_service.aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        result = await svc.send(
            to=["allowed@example.com"],
            subject="Test",
            body="body",
        )
    assert result["success"] is True
    mock_smtp.assert_awaited_once()


async def test_send_empty_whitelist_allows_all(event_bus: EventBus):
    """Empty allowed_recipients means all recipients are allowed."""
    cfg = EmailConfig(
        enabled=True,
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        username="user@example.com",
        password=SecretStr("pw"),
        imap_idle_enabled=False,
        allowed_recipients=[],
    )
    svc = EmailService(cfg, event_bus)
    svc._password_resolved = "pw"

    with patch("backend.services.email_service.aiosmtplib.send", new_callable=AsyncMock):
        result = await svc.send(
            to=["anyone@anywhere.com"],
            subject="Test",
            body="body",
        )
    assert result["success"] is True


# ---------------------------------------------------------------------------
# _decode_header
# ---------------------------------------------------------------------------


def test_decode_header_ascii():
    """Plain ASCII subject passes through unchanged."""
    assert EmailService._decode_header("Hello World") == "Hello World"


def test_decode_header_rfc2047():
    """RFC2047 encoded header is decoded correctly."""
    encoded = "=?utf-8?B?Q2nDoCBtb25kbw==?="
    result = EmailService._decode_header(encoded)
    assert result == "Cià mondo"


# ---------------------------------------------------------------------------
# _parse_email
# ---------------------------------------------------------------------------


def test_parse_email_html_stripped(service: EmailService):
    """HTML body is stripped to plain text."""
    raw = (
        b"From: a@b.com\r\n"
        b"Subject: Test\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>Hello <b>World</b></p></body></html>"
    )
    parsed = service._parse_email("1", raw)
    assert "Hello" in parsed["body"]
    assert "World" in parsed["body"]
    assert "<html>" not in parsed["body"]


def test_parse_email_body_truncation(service: EmailService):
    """Body is truncated when exceeding max_email_body_chars."""
    long_body = "A" * 200
    raw = (
        b"From: a@b.com\r\n"
        b"Subject: Test\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        + long_body.encode()
    )
    parsed = service._parse_email("1", raw)
    # max_email_body_chars=100, so body should be truncated
    assert len(parsed["body"]) <= 100 + len("\n[…troncato]")
    assert parsed["body"].endswith("[…troncato]")


# ---------------------------------------------------------------------------
# close — safe without initialized IMAP
# ---------------------------------------------------------------------------


async def test_close_without_imap(service: EmailService):
    """close() does not raise when IMAP was never connected."""
    assert service._imap is None
    await service.close()  # should not raise
