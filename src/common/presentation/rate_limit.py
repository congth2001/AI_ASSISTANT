"""Shared rate-limit dependency for FastAPI routes.

The limiter and the limits are stored on ``app.state`` by ``main.create_app``:

* ``app.state.rate_limiter``: ``SlidingWindowRateLimiter``
* ``app.state.rate_limit_config``: ``RateLimitConfig``

Usage::

    @router.post("/x", dependencies=[Depends(rate_limit("x_ip", default_limit=20))])

For keys that are not the client IP (e.g. an e-mail in the body) call
``await enforce_rate_limit(request, scope, default_limit=..., key=...)`` from a dependency.
"""
from dataclasses import dataclass, field
from typing import Callable, Mapping

from fastapi import Request

from src.common.application.rate_limiter import SlidingWindowRateLimiter, hashed_key
from src.common.errors import RateLimitedError


@dataclass(frozen=True)
class RateLimitConfig:
    window_seconds: float = 60.0
    limits: Mapping[str, int] = field(default_factory=dict)
    # Only enable behind exactly one trusted reverse proxy (ngrok, Cloudflare tunnel, nginx).
    trust_forwarded_for: bool = False


def client_ip(request: Request, *, trust_forwarded_for: bool = False) -> str:
    if trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        # The right-most entry is appended by the trusted proxy; earlier ones are client supplied.
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _state(request: Request) -> tuple[SlidingWindowRateLimiter | None, RateLimitConfig]:
    state = request.app.state
    return getattr(state, "rate_limiter", None), getattr(state, "rate_limit_config", None) or RateLimitConfig()


async def enforce_rate_limit(
    request: Request, scope: str, *, default_limit: int, key: str, hash_key: bool = False,
) -> None:
    """Raise ``RateLimitedError`` (HTTP 429 + Retry-After) when ``key`` exceeds ``scope`` limit."""
    limiter, config = _state(request)
    if limiter is None:
        return
    limit = config.limits.get(scope, default_limit)
    bucket = f"{scope}:{hashed_key(key) if hash_key else key}"
    retry_after = limiter.hit(bucket, limit, config.window_seconds)
    if retry_after:
        raise RateLimitedError(retry_after=retry_after)


def rate_limit(
    scope: str,
    *,
    default_limit: int,
    key: Callable[[Request], str] | None = None,
):
    """Build a dependency limiting requests per client IP (or a custom key) for ``scope``."""
    async def dependency(request: Request) -> None:
        _, config = _state(request)
        identity = key(request) if key else client_ip(request, trust_forwarded_for=config.trust_forwarded_for)
        await enforce_rate_limit(request, scope, default_limit=default_limit, key=identity)

    return dependency
