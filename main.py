"""
Business Chatbot - Main Application Entry Point
Clean Architecture + SOLID Principles
"""
import logging
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.config_manager import get_settings
from config.container import container
from config.settings import APISettings, normalize_origin
from src.bootstrap.logging_setup import configure_logging
from src.bootstrap.router import ROUTER_MODULES, router
from src.common.application.rate_limiter import SlidingWindowRateLimiter
from src.common.presentation.error_handlers import register_error_handlers
from src.common.presentation.rate_limit import RateLimitConfig

logger = logging.getLogger(__name__)


def resolve_cors_origins(api: APISettings, legacy_public_origins: str = "") -> list[str]:
    """Merge YAML/env origins with the legacy comma separated PUBLIC_FRONTEND_ORIGINS variable.

    Wildcards are rejected: browsers refuse `*` together with credentials and it would defeat
    the explicit allow-list.
    """
    legacy = [
        normalize_origin(origin)
        for origin in legacy_public_origins.split(",")
        if origin.strip()
    ]
    return list(dict.fromkeys([*api.cors_origins, *api.public_frontend_origins, *legacy]))


async def _close_resource(name: str, closer) -> None:
    """Shutdown must release every resource even when one of them fails."""
    try:
        await closer()
    except Exception:
        logger.exception("Failed to close %s during shutdown", name)


async def _close_redis() -> None:
    redis_client = getattr(container.cache_service(), "redis", None)
    if redis_client is not None:
        await redis_client.aclose()


async def _close_milvus() -> None:
    client = container.milvus_client()
    close = getattr(client, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result
        return
    # The Milvus adapter connects lazily; close the pymilvus connection only if it was opened.
    connection = getattr(client, "_connection", None)
    if connection is not None:
        connection.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB schema is managed by Alembic migrations — run `alembic upgrade head` before starting
    yield
    await _close_resource("Redis", _close_redis)
    await _close_resource("Milvus", _close_milvus)
    await _close_resource("PostgreSQL", container.postgres_client().close)


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    settings = get_settings()
    # Here rather than under __main__: with api.debug (reload) uvicorn builds the app
    # in a child process that never runs the __main__ block.
    if settings.logging.enabled:
        configure_logging(
            level=settings.logging.level,
            file=settings.logging.file_path(),
            max_bytes=settings.logging.max_bytes,
            backup_count=settings.logging.backup_count,
        )

    container.config.from_dict(settings.to_container_config())

    docs_enabled = settings.api.docs_enabled
    app = FastAPI(
        title="Business Chatbot API",
        description="AI-powered business assistant for data analysis and insights",
        version="1.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    rate_limit = settings.rate_limit
    app.state.rate_limiter = SlidingWindowRateLimiter(enabled=rate_limit.enabled)
    app.state.rate_limit_config = RateLimitConfig(
        window_seconds=rate_limit.window_seconds,
        limits=rate_limit.limits(),
        trust_forwarded_for=rate_limit.trust_forwarded_for,
    )

    # Keep local development origins in YAML and inject deployed frontend origins
    # at runtime, so config/local.yml never needs to be committed or rewritten.
    cors_origins = resolve_cors_origins(settings.api, os.getenv("PUBLIC_FRONTEND_ORIGINS", ""))

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "Retry-After"],
    )

    register_error_handlers(app)
    container.wire(modules=ROUTER_MODULES)
    app.include_router(router)

    return app


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:create_app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug,
        factory=True,
    )
