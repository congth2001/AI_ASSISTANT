import asyncio
import json
import logging
from contextlib import aclosing
from typing import AsyncIterator
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from dependency_injector.wiring import inject, Provide
from uuid import UUID

from config.container import Container
from src.modules.assistant.application.use_cases.chat_use_case import ChatUseCase
from src.modules.assistant.application.use_cases.search_documents_use_case import SearchDocumentsUseCase
from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.assistant.presentation.dto.chat_request import ChatRequest
from src.modules.assistant.presentation.dto.chat_response import ChatResponse
from src.modules.assistant.presentation.dto.search import SearchDocumentRequest, SearchDocumentResponse, SearchResultItem
from src.modules.auth.presentation.router import get_current_user, require_role

from src.modules.conversations.presentation.access import ensure_conversation_write_access
from src.modules.assistant.domain.errors import (
    ChatFailedError,
    ConversationIdRequiredError,
    GuestBusinessDataForbiddenError,
    DocumentSearchFailedError,
    InvalidConversationIdError,
    StreamingResponseFailedError,
)
from src.common.errors import (
    ApplicationError,
)

router = APIRouter()
logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def parse_conversation_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidConversationIdError() from exc


def _report_scope(request: ChatRequest, current_user: dict):
    """Overview report filters; guests never get business data, even pre-aggregated."""
    if request.report_context is None:
        return None
    if current_user["role"] == "guest":
        raise GuestBusinessDataForbiddenError()
    return request.report_context.to_scope()


def _sse_error() -> str:
    message = StreamingResponseFailedError().message
    return "data: " + json.dumps({"type": "error", "message": message}, ensure_ascii=False) + "\n\n"


async def _guarded_events(events: AsyncIterator[str]) -> AsyncIterator[str]:
    """Forward SSE chunks, guaranteeing a terminal `error` event on unexpected failure.

    The use cases already convert their own failures into `error` events; this
    is the last line of defence. Client disconnects (`CancelledError`) are not
    swallowed: they propagate so the use case can persist the partial answer.
    """
    try:
        async with aclosing(events):
            async for chunk in events:
                yield chunk
    except asyncio.CancelledError:
        logger.info("Chat stream cancelled by client")
        raise
    except Exception:
        logger.exception("Chat stream failed")
        yield _sse_error()


@router.post("/chat", response_model=ChatResponse)
@inject
async def chat_endpoint(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case]),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> ChatResponse:
    """Send a message and receive a full response."""
    try:
        report_scope = _report_scope(request, current_user)
        if current_user["role"] == "guest":
            return ChatResponse(**await chat_use_case.execute_guest(request.message))
        if not request.conversation_id:
            raise ConversationIdRequiredError()
        conversation_id = parse_conversation_id(request.conversation_id)
        await ensure_conversation_write_access(
            conversation_id, current_user, conversation_use_case
        )
        result = await chat_use_case.execute(
            conversation_id=conversation_id,
            user_message=request.message,
            user_id=current_user["id"],
            report_scope=report_scope,
        )
        return ChatResponse(
            conversation_id=result["conversation_id"],
            response=result["response"],
            intent=result["intent"],
            timestamp=result["timestamp"],
            metadata=result.get("metadata"),
        )
    except ApplicationError:
        raise
    except Exception as e:
        raise ChatFailedError() from e


@router.post("/chat/stream")
@inject
async def chat_stream_endpoint(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case]),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> StreamingResponse:
    """SSE streaming chat endpoint.

    Emits newline-delimited SSE events:
        data: {"type": "status",  "step": "routing|generating|cache", "message": "..."}
        data: {"type": "token",   "content": "<token>"}
        data: {"type": "done",    "conversation_id": "...", "intent": "...",
                                   "timestamp": "...", "metadata": {...}}
        data: {"type": "error",   "message": "..."}
    """
    report_scope = _report_scope(request, current_user)
    if current_user["role"] == "guest":
        # Authorize before opening the stream so a refusal is a real HTTP error
        # (403/502/...) mapped from the domain error, not an SSE event.
        try:
            await chat_use_case.authorize_guest_query(request.message)
        except ApplicationError:
            raise
        except Exception as exc:
            logger.exception("Guest query authorization failed")
            raise ChatFailedError() from exc
        return StreamingResponse(
            _guarded_events(chat_use_case.execute_guest_stream(request.message)),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    if not request.conversation_id:
        raise ConversationIdRequiredError()
    conversation_id = parse_conversation_id(request.conversation_id)
    await ensure_conversation_write_access(
        conversation_id, current_user, conversation_use_case
    )
    events = chat_use_case.execute_stream(
        conversation_id=conversation_id,
        user_message=request.message,
        user_id=current_user["id"],
        report_scope=report_scope,
    )
    return StreamingResponse(
        _guarded_events(events), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/search-documents", response_model=SearchDocumentResponse)
@inject
async def search_documents(
    request: SearchDocumentRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    search_use_case: SearchDocumentsUseCase = Depends(Provide[Container.search_documents_use_case]),
) -> SearchDocumentResponse:
    """Search for relevant business documents based on a query."""
    try:
        result = await search_use_case.execute_async(query=request.query)
        return SearchDocumentResponse(
            query=request.query,
            results=[
                SearchResultItem(
                    doc_id=r.doc_id,
                    doc_type=r.doc_type,
                    text=r.text,
                    score=r.score,
                    metadata=r.metadata,
                )
                for r in result.results
            ],
            used_fallback=result.used_fallback,
        )
    except ApplicationError:
        raise
    except Exception as e:
        raise DocumentSearchFailedError() from e
