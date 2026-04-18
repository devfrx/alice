"""Tests for backend/tools/mcp_fetch_primp.py — SSRF, redirects, clamping."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# --- Module loader --------------------------------------------------------
# The script lives outside the ``backend`` package and depends on the
# optional ``primp`` extra. Loading it via spec lets us skip cleanly when
# the dependency is absent without polluting ``backend.__init__``.

_TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "mcp_fetch_primp.py"


def _load_module():
    if not _TOOL_PATH.exists():  # pragma: no cover - layout guard
        pytest.skip("mcp_fetch_primp.py not present")
    try:
        import primp  # noqa: F401
        import bs4  # noqa: F401
        import mcp  # noqa: F401
    except Exception:
        pytest.skip("optional MCP/primp deps not installed")
    spec = importlib.util.spec_from_file_location("mcp_fetch_primp", _TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_fetch_primp"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# --- _clamp_int -----------------------------------------------------------

def test_clamp_int_handles_strings_and_floats(mod):
    assert mod._clamp_int("42", default=10, low=0, high=100) == 42
    assert mod._clamp_int(3.9, default=10, low=0, high=100) == 3
    assert mod._clamp_int("nope", default=10, low=0, high=100) == 10
    assert mod._clamp_int(None, default=10, low=0, high=100) == 10


def test_clamp_int_clamps_out_of_range(mod):
    assert mod._clamp_int(-5, default=0, low=0, high=100) == 0
    assert mod._clamp_int(10_000, default=0, low=0, high=100) == 100


# --- SSRF validation ------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_url_rejects_unc(mod):
    with pytest.raises(ValueError):
        await mod._validate_url("\\\\server\\share")


@pytest.mark.asyncio
async def test_validate_url_rejects_non_http_scheme(mod):
    with pytest.raises(ValueError):
        await mod._validate_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_validate_url_rejects_localhost(mod):
    with pytest.raises(ValueError):
        await mod._validate_url("http://localhost/")


@pytest.mark.asyncio
async def test_validate_url_rejects_private_ip_literal(mod):
    with pytest.raises(ValueError):
        await mod._validate_url("http://192.168.1.1/")


@pytest.mark.asyncio
async def test_validate_url_rejects_link_local_metadata(mod):
    with pytest.raises(ValueError):
        await mod._validate_url("http://169.254.169.254/latest/meta-data/")


# --- Redirect-aware fetch (SSRF on 3xx) -----------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, headers=None, text="", content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.mark.asyncio
async def test_redirect_to_private_ip_is_blocked(mod):
    """A 302 pointing at an internal IP must NOT be followed silently."""

    redirecting = _FakeResponse(
        status_code=302,
        headers={"location": "http://127.0.0.1/admin"},
    )

    fake_client = SimpleNamespace(get=lambda _url: redirecting)
    with patch.object(mod, "_primp", fake_client):
        with pytest.raises(ValueError):
            await mod._fetch_with_redirect_validation("https://example.com/")


@pytest.mark.asyncio
async def test_redirect_loop_capped(mod):
    """Excessive redirects raise rather than spinning forever."""

    response = _FakeResponse(
        status_code=302,
        headers={"location": "https://example.com/loop"},
    )

    async def fake_validate(_url):
        return None

    fake_client = SimpleNamespace(get=lambda _url: response)
    with patch.object(mod, "_validate_url", side_effect=fake_validate), \
         patch.object(mod, "_primp", fake_client):
        with pytest.raises(ValueError):
            await mod._fetch_with_redirect_validation("https://example.com/")


# --- call_tool argument validation ----------------------------------------
# The @server.call_tool() decorator hides the underlying function inside the
# MCP Server registry, so we exercise its building blocks (_clamp_int,
# _validate_url, _fetch_with_redirect_validation) directly above.
