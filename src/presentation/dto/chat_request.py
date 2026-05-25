from fastapi import Form
from typing import Optional


class ChatRequest:
    def __init__(
        self,
        conversation_id: str = Form(...),
        message: str = Form(...),
        user_id: Optional[str] = Form(None),
    ):
        self.conversation_id = conversation_id
        self.message = message
        self.user_id = user_id
