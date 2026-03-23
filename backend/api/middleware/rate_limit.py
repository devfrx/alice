"""AL\\CE — Rate-limiting middleware (slowapi-based)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from loguru import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse


def _key_func(request: Request) -> str:
    """Extract the client IP for rate-limiting."""
    return get_remote_address(request) or "unknown"


# Shared limiter instance — imported by route modules if per-route
# overrides are needed.
limiter = Limiter(key_func=_key_func)


async def _rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded,
) -> JSONResponse:
    """Return a JSON 429 response when rate limit is exceeded."""
    logger.warning(
        "Rate limit exceeded for {} on {}",
        _key_func(request),
        request.url.path,
    )
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


def setup_rate_limiting(app: FastAPI, default_limit: str) -> None:
    """Attach slowapi rate-limiting middleware to the application.

    Args:
        app: The FastAPI application instance.
        default_limit: Default rate limit string (e.g. ``"60/minute"``).
    """
    limiter.default_limits = [default_limit] if default_limit else []
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(
        RateLimitExceeded, _rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )
