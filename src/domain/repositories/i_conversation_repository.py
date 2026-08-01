from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from uuid import UUID


class IConversationRepository(ABC):
    """Interface for conversation repository"""

    @abstractmethod
    async def create_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new conversation"""
        pass

    @abstractmethod
    async def get_all_conversations(self, user_id: Optional[str]) -> List[Dict[str, Any]]:
        """Get all conversations"""
        pass

    @abstractmethod
    async def get_conversation(self, conversation_id: UUID, turn_limit: int, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Get conversation by ID"""
        pass

    @abstractmethod
    async def update_conversation(self, conversation_id: UUID, updates: Dict[str, Any], user_id: Optional[str]) -> bool:
        """Update conversation"""
        pass

    @abstractmethod
    async def add_message(self, conversation_id: UUID, message_data: Dict[str, Any]) -> bool:
        """Add message to conversation"""
        pass

    @abstractmethod
    async def get_conversation_messages(self, conversation_id: UUID, user_id: Optional[str], limit: int = 50) -> List[Dict[str, Any]]:
        """Get messages for a conversation"""
        pass
