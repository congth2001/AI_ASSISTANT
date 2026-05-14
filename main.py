"""
Business Chatbot - Main Application Entry Point
Clean Architecture + SOLID Principles
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.config_manager import get_settings
from config.container import container
from src.presentation.api.v1.chat import router as chat_router
from src.presentation.api.v1.reports import router as reports_router
from src.presentation.api.v1.data import router as data_router

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
    # Load settings using config manager
    settings = get_settings()

    app = FastAPI(
        title="Business Chatbot API",
        description="AI-powered business assistant for data analysis and insights",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Configure dependency injection
    container.config.from_dict(settings.model_dump())
    container.database_url.override(settings.database.url)

    # Wire dependencies
    container.wire(
        modules=[
            "src.presentation.api.v1.chat",
            "src.presentation.api.v1.reports",
            "src.presentation.api.v1.data",
        ]
    )

    # Include API routers
    app.include_router(
        chat_router,
        prefix="/api/v1",
        tags=["chat"]
    )

    app.include_router(
        reports_router,
        prefix="/api/v1",
        tags=["reports"]
    )

    app.include_router(
        data_router,
        prefix="/api/v1",
        tags=["data"]
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
