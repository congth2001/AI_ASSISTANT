from fastapi import APIRouter, Depends, Form, HTTPException
from dependency_injector.wiring import inject, Provide
from uuid import UUID

from config.container import Container
from src.application.use_cases.chat_use_case import ChatUseCase
from src.application.use_cases.search_document_use_case import SearchDocumentsUseCase
from src.presentation.dto.chat_request import ChatRequest
from src.presentation.dto.chat_response import ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
@inject
async def chat_endpoint(
    request: ChatRequest = Depends(),
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case])
) -> ChatResponse:
    """Chat endpoint for business conversations"""
    try:
        result = await chat_use_case.execute(
            conversation_id=request.conversation_id,
            user_message=request.message
        )

        return ChatResponse(
            conversation_id=result['conversation_id'],
            response=result['response'],
            intent=result['intent'],
            timestamp=result['timestamp'],
            metadata=result.get('metadata')
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


@router.get("/conversations/{conversation_id}")
@inject
async def get_conversation(
    conversation_id: UUID,
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case])
):
    """Get conversation details"""
    # This would need a separate use case for getting conversation details
    # For now, return a placeholder
    return {"conversation_id": str(conversation_id), "status": "not_implemented"}

@router.post("/conversations")
@inject
async def create_conversation(
    title: str = Form(...),
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case])
):
    """Create a new conversation"""
    # This would need a separate use case for creating conversations
    # For now, return a placeholder
    conversation_data = await chat_use_case.create_conversation(title=title)
    return conversation_data

@router.delete("/conversations/{conversation_id}")
@inject
async def delete_conversation(
    conversation_id: UUID,
    chat_use_case: ChatUseCase = Depends(Provide[Container.chat_use_case])
):
    """Delete a conversation"""
    # This would need a separate use case for deleting conversations
    # For now, return a placeholder
    return {"conversation_id": str(conversation_id), "status": "not_implemented"}


@router.post("/search-documents")
@inject
async def search_documents(
    query: str = Form(..., description="Business query to search relevant documents"),
    search_use_case: SearchDocumentsUseCase = Depends(Provide[Container.search_documents_use_case])
):
    """Search for relevant documents based on the provided query"""
    # Implementation for searching documents
    try:
        results = search_use_case.execute(query=query)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")