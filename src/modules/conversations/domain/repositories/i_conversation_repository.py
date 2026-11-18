from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from uuid import UUID

from src.modules.conversations.domain.entities.message import Message

# Upper bound for one page of the conversation list.
MAX_CONVERSATION_PAGE_SIZE = 200


class IConversationRepository(ABC):
    """Interface for conversation repository.

    Reads are scoped explicitly: by owner (``user_id`` is required and never None) or through
    the ``*_as_admin`` methods. ``user_id=None`` is never interpreted as "no filter".
    """

    @abstractmethod
    async def create_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new conversation"""
        pass

    @abstractmethod
    async def list_conversations_for_owner(
        self, owner_id: str, limit: int = MAX_CONVERSATION_PAGE_SIZE, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Conversations owned by ``owner_id``, most recently updated first."""
        pass

    @abstractmethod
    async def list_conversations_as_admin(
        self, limit: int = MAX_CONVERSATION_PAGE_SIZE, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Conversations of every account, most recently updated first (admin only)."""
        pass

    @abstractmethod
    async def get_conversation(
        self, conversation_id: UUID, turn_limit: int, user_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Get a conversation owned by ``user_id``; raises ConversationScopeRequiredError if None."""
        pass

    @abstractmethod
    async def get_conversation_as_admin(
        self, conversation_id: UUID, turn_limit: int
    ) -> Optional[Dict[str, Any]]:
        """Get any (non-deleted) conversation regardless of owner; admin read-only use."""
        pass

    @abstractmethod
    async def update_conversation(self, conversation_id: UUID, updates: Dict[str, Any], user_id: Optional[str]) -> bool:
        """Update an owned conversation; raises ConversationScopeRequiredError if user_id is None."""
        pass

    @abstractmethod
    async def add_messages(self, conversation_id: UUID, messages: List[Dict[str, Any]]) -> List[Message]:
        """Persist several messages in ONE transaction and bump ``conversations.updated_at``.

        Each dict needs ``role`` and ``content``; ``metadata`` (may be None), ``id`` and
        ``timestamp`` are optional. Raises ConversationNotFoundError when the conversation
        does not exist or is deleted (nothing is written).
        """
        pass
