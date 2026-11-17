import json
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
    DocumentSearchFailedError,
    InvalidConversationIdError,
    StreamingResponseFailedError,
)
from src.common.errors import (
    ApplicationError,
)

router = APIRouter()


def parse_conversation_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidConversationIdError() from exc


@router.post("/chat", response_model=ChatResponse)
@inject
async def chat_endpoint(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case]),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> ChatResponse:
    """Send a message and receive a full response."""
    try:
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
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> StreamingResponse:
    """SSE streaming chat endpoint.

    Emits newline-delimited SSE events:
        data: {"type": "status",  "step": "routing|generating|cache", "message": "..."}
        data: {"type": "token",   "content": "<token>"}
        data: {"type": "done",    "conversation_id": "...", "intent": "...",
                                   "timestamp": "...", "metadata": {...}}
        data: {"type": "error",   "message": "..."}
    """
    if current_user["role"] == "guest":
        await chat_use_case.authorize_guest_query(request.message)

        return StreamingResponse(
            chat_use_case.execute_guest_stream(request.message),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    if not request.conversation_id:
        raise ConversationIdRequiredError()
    conversation_id = parse_conversation_id(request.conversation_id)
    await ensure_conversation_write_access(
        conversation_id, current_user, conversation_use_case
    )

    async def event_generator():
        try:
            async for chunk in chat_use_case.execute_stream(
                conversation_id=conversation_id,
                user_message=request.message,
                user_id=current_user["id"],
            ):
                yield chunk
        except Exception:
            error = StreamingResponseFailedError()
            yield f"data: {json.dumps({'type': 'error', 'message': error.message})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
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
        result = search_use_case.execute(query=request.query)
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
