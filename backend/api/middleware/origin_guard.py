"""AL\\CE — Origin validation middleware for mutable endpoints.

Prevents cross-origin requests from untrusted web pages to sensitive
endpoints (e.g. PUT /config, PUT /settings). Since AL\\CE runs locally,
this guards against malicious JS on arbitrary websites calling the
local API to disable security features.

Safe/read-only methods (GET, HEAD, OPTIONS) are always allowed.
WebSocket upgrades are excluded (handled by their own connection logic).
"""

from __future__ import annotations

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


# Fallback trusted origins when none are provided via config.
_DEFAULT_TRUSTED: set[str] = {
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "null",
}

# HTTP methods considered safe (read-only).
_SAFE_METHODS: set[str] = {"GET", "HEAD", "OPTIONS"}


def _expand_origins(origins: list[str]) -> set[str]:
    """Expand a list of origins to include 127.0.0.1 equivalents.

    Ensures that ``localhost`` and ``127.0.0.1`` variants are
    both trusted when either is configured.

    Args:
        origins: Origins from ``config.server.cors_origins``.

    Returns:
        Expanded set including 127.0.0.1 equivalents.
    """
    expanded: set[str] = set()
    for origin in origins:
        expanded.add(origin)
        if "://localhost:" in origin:
            expanded.add(
                origin.replace("://localhost:", "://127.0.0.1:")
            )
        elif "://127.0.0.1:" in origin:
            expanded.add(
                origin.replace("://127.0.0.1:", "://localhost:")
            )
    return expanded


class OriginGuardMiddleware:
    """Block mutable HTTP requests from untrusted origins.

    Checks the ``Origin`` header on non-safe HTTP methods.  If the
    origin is missing or not in the trusted set, the request is
    rejected with 403 Forbidden.

    WebSocket connections and safe methods are always allowed.

    Args:
        app: The inner ASGI application.
        trusted_origins: Origins to trust for mutable requests.
            When provided, ``localhost``/``127.0.0.1`` equivalents
            are added automatically.  Defaults to common dev origins.
    """

    def __init__(
        self,
        app: ASGIApp,
        trusted_origins: list[str] | None = None,
    ) -> None:
        self.app = app
        if trusted_origins is not None:
            self._trusted = _expand_origins(trusted_origins)
        else:
            self._trusted = _DEFAULT_TRUSTED

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        method = request.method.upper()

        if method in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        origin = request.headers.get("origin", "")

        # Allow requests with no Origin header (same-origin requests
        # from non-browser clients like curl, httpie, Postman).
        if not origin:
            await self.app(scope, receive, send)
            return

        if origin not in self._trusted:
            logger.warning(
                "Blocked mutable request from untrusted origin: {} {} (origin={})",
                method, request.url.path, origin,
            )
            response = JSONResponse(
                status_code=403,
                content={"detail": "Request blocked: untrusted origin"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
