from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    user_id: Optional[str] = None
