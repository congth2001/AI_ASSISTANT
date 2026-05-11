from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from uuid import UUID
import uuid

from src.application.use_cases.chat_use_case import ChatUseCase
from src.application.dto.chat_request import ChatRequest
from src.application.dto.chat_response import ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    chat_use_case: ChatUseCase = Depends()
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
async def get_conversation(
    conversation_id: UUID,
    chat_use_case: ChatUseCase = Depends()
):
    """Get conversation details"""
    # This would need a separate use case for getting conversation details
    # For now, return a placeholder
    return {"conversation_id": str(conversation_id), "status": "not_implemented"}