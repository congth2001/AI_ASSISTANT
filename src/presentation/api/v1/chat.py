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

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
@inject
async def chat_endpoint(
    request: ChatRequest,
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case]),
) -> ChatResponse:
    """Send a message and receive a full response."""
    try:
        result = await chat_use_case.execute(
            conversation_id=request.conversation_id,
            user_message=request.message,
        )
        return ChatResponse(
            conversation_id=result["conversation_id"],
            response=result["response"],
            intent=result["intent"],
            timestamp=result["timestamp"],
            metadata=result.get("metadata"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


@router.post("/chat/stream")
@inject
async def chat_stream_endpoint(
    request: ChatRequest,
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case]),
) -> StreamingResponse:
    """SSE streaming chat endpoint.

    Emits newline-delimited SSE events:
        data: {"type": "status",  "step": "routing|generating|cache", "message": "..."}
        data: {"type": "token",   "content": "<token>"}
        data: {"type": "done",    "conversation_id": "...", "intent": "...",
                                   "timestamp": "...", "metadata": {...}}
        data: {"type": "error",   "message": "..."}
    """
    async def event_generator():
        try:
            async for chunk in chat_use_case.execute_stream(
                conversation_id=UUID(request.conversation_id),
                user_message=request.message,
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
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> ConversationResponse:
    """Get conversation details including message history."""
    try:
        data = await conversation_use_case.get_conversation(conversation_id)
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
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> List[ConversationResponse]:
    """Get all conversations."""
    try:
        data_list = await conversation_use_case.get_all_conversations()
        return [ConversationResponse(**data) for data in data_list]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving conversations: {str(e)}")


@router.post("/conversations", response_model=CreateConversationResponse, status_code=201)
@inject
async def create_conversation(
    request: CreateConversationRequest,
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> CreateConversationResponse:
    """Create a new conversation."""
    try:
        data = await conversation_use_case.create_conversation(
            title=request.title,
            user_id=request.user_id,
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
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> ConversationResponse:
    """Rename a conversation."""
    try:
        success = await conversation_use_case.rename_conversation(conversation_id, request.title)
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        data = await conversation_use_case.get_conversation(conversation_id)
        return ConversationResponse(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error renaming conversation: {str(e)}")


@router.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
@inject
async def delete_conversation(
    conversation_id: UUID,
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> DeleteConversationResponse:
    """Soft-delete a conversation."""
    try:
        result = await conversation_use_case.delete_conversation(conversation_id)
        return DeleteConversationResponse(
            conversation_id=str(conversation_id),
            status="deleted" if result else "not_found",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting conversation: {str(e)}")


@router.post("/search-documents", response_model=SearchDocumentResponse)
@inject
async def search_documents(
    request: SearchDocumentRequest,
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
