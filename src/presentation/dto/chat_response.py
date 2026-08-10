from pydantic import BaseModel
from typing import Optional, Dict, Any


class ChatResponse(BaseModel):
    conversation_id: Optional[str] = None
    response: str
    intent: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None
