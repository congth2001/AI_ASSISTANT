from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime


class ChatRequest(BaseModel):
    """DTO for chat request"""
    conversation_id: UUID
    message: str
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """DTO for chat response"""
    conversation_id: str
    response: str
    intent: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None