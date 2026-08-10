from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from src.domain.entities.message import Message
from src.domain.time import now_vietnam

@dataclass
class Conversation:
    """Entity representing a conversation session"""
    id: Optional[UUID] = None
    user_id: Optional[str] = None
    title: Optional[str] = None
    messages: List[Message] = None
    created_at: datetime = None
    updated_at: datetime = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.messages is None:
            self.messages = []
        if self.created_at is None:
            self.created_at = now_vietnam()
        if self.updated_at is None:
            self.updated_at = now_vietnam()

    def add_message(self, message: Message):
        self.messages.append(message)
        self.updated_at = now_vietnam()
