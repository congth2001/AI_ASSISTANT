"""
Business Chatbot - Main Application Entry Point
Clean Architecture + SOLID Principles
"""
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.config_manager import get_settings
from config.container import container
from src.presentation.api.v1.chat import router as chat_router
from src.presentation.api.v1.auth import router as auth_router
from src.presentation.api.v1.analytics import router as analytics_router

def init_config_connections():
    """Initialize connections to external services based on config"""
    settings = get_settings()

    # Initialize vector database connection
    # This is a placeholder - actual implementation would depend on the vector DB used
    # For example, if using Milvus:
    # vector_db_client = MilvusClient(host=settings.vector_db.host, port=settings.vector_db.port)
    # container.vector_db.override(vector_db_client)

def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    settings = get_settings()

    container.config.from_dict(settings.model_dump())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # DB schema is managed by Alembic migrations — run `alembic upgrade head` before starting
        yield

    app = FastAPI(
        title="Business Chatbot API",
        description="AI-powered business assistant for data analysis and insights",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Keep local development origins in YAML and inject deployed frontend origins
    # at runtime, so config/local.yml never needs to be committed or rewritten.
    cors_origins = list(settings.api.cors_origins)
    public_origins = os.getenv("PUBLIC_FRONTEND_ORIGINS", "")
    cors_origins.extend(
        origin.strip().rstrip("/")
        for origin in public_origins.split(",")
        if origin.strip()
    )
    cors_origins = list(dict.fromkeys(cors_origins))

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wire dependencies
    container.wire(
        modules=[
            "src.presentation.api.v1.chat",
            "src.presentation.api.v1.auth",
            "src.presentation.api.v1.analytics",
        ]
    )

    # Include API routers
    app.include_router(
        chat_router,
        prefix="/api/v1",
        tags=["chat"]
    )
    app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
    app.include_router(
        analytics_router,
        prefix="/api/v1",
        tags=["analytics"],
    )


    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "business-chatbot"}

    # Root endpoint
    @app.get("/")
    async def root():
        return {
            "message": "Business Chatbot API",
            "version": "1.0.0",
            "docs": "/docs"
        }

    return app


if __name__ == "__main__":
    settings = get_settings()
    app = create_app()
    uvicorn.run(
        app,
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug
    )
