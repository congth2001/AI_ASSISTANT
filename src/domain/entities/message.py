from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from uuid import UUID


@dataclass
class Message:
    """Entity representing a chat message"""
    id: Optional[UUID] = None
    conversation_id: UUID
    content: str
    role: str  # 'user' or 'assistant'
    timestamp: datetime = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


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
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()

    def add_message(self, message: Message):
        self.messages.append(message)
        self.updated_at = datetime.now()