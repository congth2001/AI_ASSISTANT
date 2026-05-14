from pydantic import BaseModel
from typing import Optional, Dict, Any
from uuid import UUID


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: str
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
