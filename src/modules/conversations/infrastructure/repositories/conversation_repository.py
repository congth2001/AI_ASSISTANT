from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import select, update

from src.common.domain.time import as_vietnam_time
from src.common.infrastructure.database.orm_utils import model_to_dict
from src.modules.auth.infrastructure.models import UserModel
from src.modules.conversations.domain.entities.message import Message
from src.modules.conversations.domain.errors import (
    ConversationNotFoundError,
    ConversationScopeRequiredError,
)
from src.modules.conversations.domain.repositories.i_conversation_repository import (
    MAX_CONVERSATION_PAGE_SIZE,
    IConversationRepository,
)
from src.modules.conversations.infrastructure.models import ConversationModel, MessageModel


def _clamp_page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(int(limit), MAX_CONVERSATION_PAGE_SIZE)), max(0, int(offset))


class ConversationRepository(IConversationRepository):
    """SQLAlchemy implementation of conversation repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _to_dict(model) -> Dict[str, Any]:
        data = model_to_dict(model)
        for field in ("created_at", "updated_at", "deleted_at"):
            if field in data:
                data[field] = as_vietnam_time(data[field])
        return data

    @staticmethod
    def _owner_to_dict(user: Optional[UserModel]) -> Optional[Dict[str, Any]]:
        if user is None:
            return None
        return {
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role,
        }

    @staticmethod
    def _require_owner(user_id: Optional[str]) -> str:
        """Owner scoped methods never fall back to 'all conversations' for a missing owner."""
        if user_id is None:
            raise ConversationScopeRequiredError()
        return user_id

    async def create_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new conversation"""
        async with self.session_factory() as session:
            conversation = ConversationModel(
                id=str(uuid4()),
                user_id=conversation_data.get('user_id'),
                title=conversation_data.get('title'),
                extra_metadata=conversation_data.get('metadata'),
            )
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
            owner = await session.get(UserModel, conversation.user_id)
            return {
                **self._to_dict(conversation),
                "owner": self._owner_to_dict(owner),
            }

    async def _list(self, conditions: list, limit: int, offset: int) -> List[Dict[str, Any]]:
        limit, offset = _clamp_page(limit, offset)
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationModel, UserModel)
                .outerjoin(UserModel, UserModel.id == ConversationModel.user_id)
                .where(ConversationModel.deleted_at.is_(None), *conditions)
                # id as tie breaker keeps pagination stable for equal timestamps.
                .order_by(ConversationModel.updated_at.desc().nulls_last(), ConversationModel.id)
                .limit(limit)
                .offset(offset)
            )
            return [
                {**self._to_dict(conversation), "owner": self._owner_to_dict(owner)}
                for conversation, owner in result.all()
            ]

    async def list_conversations_for_owner(
        self, owner_id: str, limit: int = MAX_CONVERSATION_PAGE_SIZE, offset: int = 0
    ) -> List[Dict[str, Any]]:
        owner_id = self._require_owner(owner_id)
        return await self._list([ConversationModel.user_id == owner_id], limit, offset)

    async def list_conversations_as_admin(
        self, limit: int = MAX_CONVERSATION_PAGE_SIZE, offset: int = 0
    ) -> List[Dict[str, Any]]:
        return await self._list([], limit, offset)

    async def _get_with_messages(
        self, conversation_id: UUID, turn_limit: int, owner_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Authorize first (single query), then load messages only for a visible conversation."""
        conv_id_str = str(conversation_id)
        conditions = [
            ConversationModel.id == conv_id_str,
            ConversationModel.deleted_at.is_(None),
        ]
        if owner_id is not None:
            conditions.append(ConversationModel.user_id == owner_id)

        async with self.session_factory() as session:
            found = (
                await session.execute(
                    select(ConversationModel, UserModel)
                    .outerjoin(UserModel, UserModel.id == ConversationModel.user_id)
                    .where(*conditions)
                )
            ).one_or_none()
            if found is None:
                return None
            conv_row, owner_row = found

            msg_rows = (
                await session.execute(
                    select(MessageModel)
                    .where(
                        MessageModel.conversation_id == conv_id_str,
                        MessageModel.deleted_at.is_(None),
                        MessageModel.created_at.isnot(None),
                    )
                    .order_by(MessageModel.created_at.desc())
                    .limit(turn_limit * 2)
                )
            ).scalars().all()

        conv_data = self._to_dict(conv_row)
        conv_data["owner"] = self._owner_to_dict(owner_row)
        conv_data["messages"] = []
        for message in msg_rows:  # already DESC (newest first)
            message_data = self._to_dict(message)
            message_data["timestamp"] = message_data.pop("created_at", None)
            conv_data["messages"].append(message_data)
        return conv_data

    async def get_conversation(
        self, conversation_id: UUID, turn_limit: int = 10, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get an owned conversation with the specified number of most recent turns."""
        return await self._get_with_messages(conversation_id, turn_limit, self._require_owner(user_id))

    async def get_conversation_as_admin(
        self, conversation_id: UUID, turn_limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        return await self._get_with_messages(conversation_id, turn_limit, None)

    async def update_conversation(
        self, conversation_id: UUID, updates: Dict[str, Any], user_id: Optional[str]
    ) -> bool:
        """Update an owned conversation"""
        owner_id = self._require_owner(user_id)
        async with self.session_factory() as session:
            result = await session.execute(
                update(ConversationModel)
                .where(
                    ConversationModel.id == str(conversation_id),
                    ConversationModel.deleted_at.is_(None),
                    ConversationModel.user_id == owner_id,
                )
                .values(**updates)
            )
            await session.commit()
            return result.rowcount > 0

    async def add_messages(self, conversation_id: UUID, messages: List[Dict[str, Any]]) -> List[Message]:
        """Persist messages atomically: either every message is stored or none is."""
        if not messages:
            return []
        conv_id_str = str(conversation_id)
        now = datetime.now(timezone.utc)
        models: list[MessageModel] = []
        for index, data in enumerate(messages):
            models.append(MessageModel(
                id=str(data.get('id') or uuid4()),
                conversation_id=conv_id_str,
                content=data['content'],
                role=data['role'],
                extra_metadata=data.get('metadata'),
                # Strictly increasing timestamps keep the intended order inside one transaction.
                created_at=data.get('timestamp') or now + timedelta(microseconds=index),
            ))

        async with self.session_factory() as session, session.begin():
            touched = await session.execute(
                update(ConversationModel)
                .where(ConversationModel.id == conv_id_str, ConversationModel.deleted_at.is_(None))
                .values(updated_at=now)
            )
            if touched.rowcount == 0:
                raise ConversationNotFoundError()
            session.add_all(models)

        return [
            Message(
                id=UUID(model.id),
                conversation_id=conversation_id if isinstance(conversation_id, UUID) else UUID(conv_id_str),
                content=model.content,
                role=model.role,
                timestamp=as_vietnam_time(model.created_at),
                metadata=model.extra_metadata,
            )
            for model in models
        ]
