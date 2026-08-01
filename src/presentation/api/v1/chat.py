import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from dependency_injector.wiring import inject, Provide
from uuid import UUID

from config.container import Container
from src.application.use_cases.chat_use_case import ChatUseCase
from src.application.use_cases.search_document_use_case import SearchDocumentsUseCase
from src.application.use_cases.conversation_use_case import ConversationUseCase
from src.presentation.dto.chat_request import ChatRequest
from src.presentation.dto.chat_response import ChatResponse
from src.presentation.dto.conversation import (
    CreateConversationRequest,
    CreateConversationResponse,
    ConversationResponse,
    DeleteConversationResponse,
    RenameConversationRequest,
)
from src.presentation.dto.search import SearchDocumentRequest, SearchDocumentResponse, SearchResultItem
from src.presentation.api.v1.auth import get_current_user, require_role

router = APIRouter()


def conversation_read_scope(current_user: dict) -> str | None:
    """Admins can read every conversation; staff can read only their own."""
    return None if current_user["role"] == "admin" else current_user["id"]


async def ensure_conversation_write_access(
    conversation_id: UUID,
    current_user: dict,
    conversation_use_case: ConversationUseCase,
) -> None:
    """Only the owner can chat in, rename, or delete a conversation."""
    owned = await conversation_use_case.get_conversation(
        conversation_id, current_user["id"], turn_limit=1
    )
    if owned:
        return

    if current_user["role"] == "admin":
        visible = await conversation_use_case.get_conversation(
            conversation_id, None, turn_limit=1
        )
        if visible:
            raise HTTPException(
                status_code=403,
                detail="Conversation của tài khoản khác chỉ được phép xem",
            )
    raise HTTPException(status_code=404, detail="Conversation not found")


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
            raise HTTPException(status_code=400, detail="conversation_id is required")
        conversation_id = UUID(request.conversation_id)
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
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


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
        try:
            await chat_use_case.authorize_guest_query(request.message)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        return StreamingResponse(
            chat_use_case.execute_guest_stream(request.message),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    if not request.conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    conversation_id = UUID(request.conversation_id)
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
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def get_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> ConversationResponse:
    """Get conversation details including message history."""
    try:
        data = await conversation_use_case.get_conversation(
            conversation_id, conversation_read_scope(current_user)
        )
        if not data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if data.get("messages"):
            data["messages"] = list(reversed(data["messages"]))
        return ConversationResponse(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving conversation: {str(e)}")

@router.get("/conversations", response_model=List[ConversationResponse])
@inject
async def get_all_conversations(
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> List[ConversationResponse]:
    """Get all conversations."""
    try:
        data_list = await conversation_use_case.get_all_conversations(
            conversation_read_scope(current_user)
        )
        return [ConversationResponse(**data) for data in data_list]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving conversations: {str(e)}")


@router.post("/conversations", response_model=CreateConversationResponse, status_code=201)
@inject
async def create_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> CreateConversationResponse:
    """Create a new conversation."""
    try:
        data = await conversation_use_case.create_conversation(
            title=request.title,
            user_id=current_user["id"],
            metadata=request.metadata,
        )
        return CreateConversationResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating conversation: {str(e)}")


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def rename_conversation(
    conversation_id: UUID,
    request: RenameConversationRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> ConversationResponse:
    """Rename a conversation."""
    try:
        await ensure_conversation_write_access(
            conversation_id, current_user, conversation_use_case
        )
        success = await conversation_use_case.rename_conversation(
            conversation_id, request.title, current_user["id"]
        )
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        data = await conversation_use_case.get_conversation(
            conversation_id, current_user["id"]
        )
        return ConversationResponse(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error renaming conversation: {str(e)}")


@router.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
@inject
async def delete_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> DeleteConversationResponse:
    """Soft-delete a conversation."""
    try:
        await ensure_conversation_write_access(
            conversation_id, current_user, conversation_use_case
        )
        result = await conversation_use_case.delete_conversation(
            conversation_id, current_user["id"]
        )
        return DeleteConversationResponse(
            conversation_id=str(conversation_id),
            status="deleted" if result else "not_found",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting conversation: {str(e)}")


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")
