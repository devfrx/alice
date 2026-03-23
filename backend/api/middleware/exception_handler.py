"""AL\\CE — ASGI middleware for unhandled exception safety net.

Placed inside CORSMiddleware so error responses always carry CORS headers,
even when SlowAPI's BaseHTTPMiddleware interferes with exception propagation.
"""

from __future__ import annotations

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class UnhandledExceptionMiddleware:
    """Catch exceptions escaping inner middleware and return a JSON 500.

    This middleware acts as a safety net between CORSMiddleware (outer)
    and SlowAPIMiddleware (inner).  When an exception bypasses FastAPI's
    built-in ExceptionMiddleware — e.g. because BaseHTTPMiddleware
    intercepts it first — this layer ensures a proper JSON response is
    returned through the CORS pipeline.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False
        original_send = send

        async def _send_wrapper(message: dict) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await original_send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        except Exception as exc:
            if response_started:
                raise  # Headers already sent — nothing we can do
            request = Request(scope)
            logger.opt(exception=exc).error(
                "Unhandled exception on {} {}", request.method, request.url.path,
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )
            await response(scope, receive, original_send)
