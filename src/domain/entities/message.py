from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4


@dataclass
class Message:
    """Entity representing a chat message"""
    id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    content: str = ""
    role: str = "user"  # 'user' or 'assistant'
    timestamp: datetime = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.id is None:
            self.id = uuid4()

        if self.timestamp is None:
            self.timestamp = datetime.now()
