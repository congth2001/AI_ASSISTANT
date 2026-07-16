from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime


class CreateConversationRequest(BaseModel):
    title: Optional[str] = "New Conversation"
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RenameConversationRequest(BaseModel):
    title: str


class MessageResponse(BaseModel):
    role: str
    content: str
    timestamp: Optional[datetime] = None


class ConversationResponse(BaseModel):
    id: str
    title: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: Optional[List[MessageResponse]] = None
    metadata: Optional[Dict[str, Any]] = None


class CreateConversationResponse(BaseModel):
    id: str
    title: str
    user_id: Optional[str] = None
    created_at: Optional[datetime] = None


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    status: str
