from typing import Any, Dict, List, Optional
from uuid import UUID

from src.domain.repositories.i_conversation_repository import IConversationRepository
from src.domain.time import now_vietnam


class ConversationUseCase:
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

    async def get_conversation(
        self,
        conversation_id: UUID,
        user_id: Optional[str],
        turn_limit: int = 50,
    ) -> Optional[Dict[str, Any]]:
        return await self.conversation_repo.get_conversation(conversation_id, turn_limit, user_id)

    async def get_all_conversations(self, user_id: Optional[str]) -> List[Dict[str, Any]]:
        return await self.conversation_repo.get_all_conversations(user_id)

    async def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
        user_id: Optional[str],
    ) -> bool:
        return await self.conversation_repo.update_conversation(
            conversation_id,
            {"title": title, "updated_at": now_vietnam()},
            user_id,
        )

    async def delete_conversation(self, conversation_id: UUID, user_id: Optional[str]) -> bool:
        return await self.conversation_repo.update_conversation(
            conversation_id,
            {"deleted_at": now_vietnam()},
            user_id,
        )

    async def get_messages(
        self,
        conversation_id: UUID,
        user_id: Optional[str],
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return await self.conversation_repo.get_conversation_messages(conversation_id, user_id, limit)
