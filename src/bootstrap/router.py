"""HTTP composition: aggregate module routers and public service endpoints."""
from fastapi import APIRouter, Request

from src.modules.assistant.presentation import router as chat_routes
from src.modules.auth.presentation import router as auth_routes
from src.modules.conversations.presentation import router as conversation_routes
from src.modules.analytics.presentation import router as analytics_routes


# Keep DI wiring beside the route registrations so new modules have one entry point.
ROUTER_MODULES = (chat_routes, auth_routes, conversation_routes, analytics_routes)

router = APIRouter()
router.include_router(chat_routes.router, prefix="/api/v1", tags=["chat"])
router.include_router(auth_routes.router, prefix="/api/v1", tags=["auth"])
router.include_router(conversation_routes.router, prefix="/api/v1", tags=["conversations"])
router.include_router(analytics_routes.router, prefix="/api/v1", tags=["analytics"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "business-chatbot"}


@router.get("/")
async def root(request: Request):
    return {
        "message": "Business Chatbot API",
        "version": "1.0.0",
        # Swagger can be disabled via api.docs_enabled.
        "docs": request.app.docs_url,
    }
