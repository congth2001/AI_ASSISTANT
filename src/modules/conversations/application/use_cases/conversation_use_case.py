import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from src.modules.conversations.domain.entities.message import Message
from src.modules.conversations.domain.errors import ConversationScopeRequiredError
from src.modules.conversations.domain.repositories.i_conversation_repository import (
    MAX_CONVERSATION_PAGE_SIZE,
    IConversationRepository,
)
from src.common.domain.time import now_vietnam

logger = logging.getLogger(__name__)


class ConversationUseCase:
    """Conversation queries are always scoped: by owner, or explicitly as admin."""

    def __init__(self, conversation_repo: IConversationRepository):
        self.conversation_repo = conversation_repo

    async def create_conversation(
        self,
        title: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self.conversation_repo.create_conversation(
            {"title": title or "New Conversation", "user_id": user_id, "metadata": metadata}
        )

    async def get_conversation_for_owner(
        self, conversation_id: UUID, owner_id: str, turn_limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Conversation visible to its owner only."""
        return await self.conversation_repo.get_conversation(conversation_id, turn_limit, owner_id)

    async def get_conversation_as_admin(
        self, conversation_id: UUID, turn_limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Any conversation. Callers must have verified the admin role (read-only access)."""
        return await self.conversation_repo.get_conversation_as_admin(conversation_id, turn_limit)

    async def get_conversation(
        self,
        conversation_id: UUID,
        user_id: Optional[str],
        turn_limit: int = 50,
    ) -> Optional[Dict[str, Any]]:
        """Owner scoped read kept for existing callers (``user_id`` is the owner).

        ``user_id=None`` used to mean "no filter"; that is now refused. Use
        ``get_conversation_as_admin`` after checking the admin role instead.
        """
        if user_id is None:
            logger.error("Unscoped get_conversation call refused; use get_conversation_as_admin")
            raise ConversationScopeRequiredError()
        return await self.get_conversation_for_owner(conversation_id, user_id, turn_limit)

    async def get_conversations_for_owner(
        self, owner_id: str, limit: int = MAX_CONVERSATION_PAGE_SIZE, offset: int = 0
    ) -> List[Dict[str, Any]]:
        return await self.conversation_repo.list_conversations_for_owner(owner_id, limit, offset)

    async def get_all_conversations_as_admin(
        self, limit: int = MAX_CONVERSATION_PAGE_SIZE, offset: int = 0
    ) -> List[Dict[str, Any]]:
        return await self.conversation_repo.list_conversations_as_admin(limit, offset)

    async def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
        user_id: str,
    ) -> bool:
        return await self.conversation_repo.update_conversation(
            conversation_id,
            {"title": title, "updated_at": now_vietnam()},
            user_id,
        )

    async def delete_conversation(self, conversation_id: UUID, user_id: str) -> bool:
        return await self.conversation_repo.update_conversation(
            conversation_id,
            {"deleted_at": now_vietnam()},
            user_id,
        )

    async def add_messages(
        self, conversation_id: UUID, messages: List[Dict[str, Any]]
    ) -> List[Message]:
        """Persist several messages atomically (see ``IConversationRepository.add_messages``)."""
        return await self.conversation_repo.add_messages(conversation_id, messages)
