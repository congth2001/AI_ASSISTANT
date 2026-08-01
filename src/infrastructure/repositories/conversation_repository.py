import asyncio
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import select, update

from src.domain.repositories.i_conversation_repository import IConversationRepository
from src.domain.time import as_vietnam_time
from src.infrastructure.repositories.models import ConversationModel, MessageModel, UserModel


class ConversationRepository(IConversationRepository):
    """SQLAlchemy implementation of conversation repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _to_dict(model) -> Dict[str, Any]:
        data = {
            key: value
            for key, value in model.__dict__.items()
            if not key.startswith("_")
        }
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

    async def get_all_conversations(self, user_id: Optional[str]) -> List[Dict[str, Any]]:
        """Get all conversations"""
        async with self.session_factory() as session:
            conditions = [ConversationModel.deleted_at.is_(None)]
            if user_id is not None:
                conditions.append(ConversationModel.user_id == user_id)
            result = await session.execute(
                select(ConversationModel, UserModel)
                .outerjoin(UserModel, UserModel.id == ConversationModel.user_id)
                .where(*conditions)
            )
            return [
                {
                    **self._to_dict(conversation),
                    "owner": self._owner_to_dict(owner),
                }
                for conversation, owner in result.all()
            ]

    async def get_conversation(
        self, conversation_id: UUID, turn_limit: int = 10, user_id: Optional[str] = ""
    ) -> Optional[Dict[str, Any]]:
        """Get conversation by ID with specified number of most recent turns"""
        conv_id_str = str(conversation_id)

        async def _fetch_conversation():
            async with self.session_factory() as session:
                conditions = [
                    ConversationModel.id == conv_id_str,
                    ConversationModel.deleted_at.is_(None),
                ]
                if user_id is not None:
                    conditions.append(ConversationModel.user_id == user_id)
                result = await session.execute(
                    select(ConversationModel, UserModel)
                    .outerjoin(UserModel, UserModel.id == ConversationModel.user_id)
                    .where(*conditions)
                )
                return result.one_or_none()

        async def _fetch_messages():
            async with self.session_factory() as session:
                result = await session.execute(
                    select(MessageModel)
                    .where(
                        MessageModel.conversation_id == conv_id_str,
                        MessageModel.deleted_at.is_(None),
                        MessageModel.created_at.isnot(None),
                    )
                    .order_by(MessageModel.created_at.desc())
                    .limit(turn_limit * 2)
                )
                return result.scalars().all()

        conversation_result, msg_rows = await asyncio.gather(
            _fetch_conversation(), _fetch_messages()
        )

        if conversation_result is None:
            return None
        conv_row, owner_row = conversation_result

        conv_data = self._to_dict(conv_row)
        conv_data["owner"] = self._owner_to_dict(owner_row)
        conv_data["messages"] = []
        for message in msg_rows:  # already DESC (newest first)
            message_data = self._to_dict(message)
            message_data["timestamp"] = message_data.pop("created_at", None)
            conv_data["messages"].append(message_data)
        return conv_data

    async def update_conversation(
        self, conversation_id: UUID, updates: Dict[str, Any], user_id: Optional[str]
    ) -> bool:
        """Update conversation"""
        async with self.session_factory() as session:
            conditions = [
                ConversationModel.id == str(conversation_id),
                ConversationModel.deleted_at.is_(None),
            ]
            if user_id is not None:
                conditions.append(ConversationModel.user_id == user_id)
            result = await session.execute(
                update(ConversationModel).where(*conditions).values(**updates)
            )
            await session.commit()
            return result.rowcount > 0

    async def add_message(self, conversation_id: UUID, message_data: Dict[str, Any]) -> bool:
        """Add message to conversation"""
        async with self.session_factory() as session:
            message = MessageModel(
                id=message_data['id'],
                conversation_id=str(conversation_id),
                content=message_data['content'],
                role=message_data['role'],
                extra_metadata=message_data.get('metadata'),
            )
            session.add(message)
            await session.commit()
            return True

    async def get_conversation_messages(
        self, conversation_id: UUID, user_id: Optional[str], limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get messages for a conversation"""
        async with self.session_factory() as session:
            conditions = [MessageModel.conversation_id == str(conversation_id)]
            if user_id is not None:
                conditions.append(ConversationModel.user_id == user_id)
            result = await session.execute(
                select(MessageModel)
                .join(ConversationModel, ConversationModel.id == MessageModel.conversation_id)
                .where(*conditions)
                .order_by(MessageModel.created_at.asc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [self._to_dict(row) for row in rows]
