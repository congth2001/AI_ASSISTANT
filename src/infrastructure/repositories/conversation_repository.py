import asyncio
from datetime import timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import select, update

from src.domain.repositories.i_conversation_repository import IConversationRepository
from src.infrastructure.repositories.models import ConversationModel, MessageModel


class ConversationRepository(IConversationRepository):
    """SQLAlchemy implementation of conversation repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

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
            return conversation.__dict__

    async def get_all_conversations(self) -> List[Dict[str, Any]]:
        """Get all conversations"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationModel).where(ConversationModel.deleted_at.is_(None))
            )
            rows = result.scalars().all()
            return [row.__dict__ for row in rows]

    async def get_conversation(self, conversation_id: UUID, turn_limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get conversation by ID with specified number of most recent turns"""
        conv_id_str = str(conversation_id)

        async def _fetch_conversation():
            async with self.session_factory() as session:
                result = await session.execute(
                    select(ConversationModel).where(
                        ConversationModel.id == conv_id_str,
                        ConversationModel.deleted_at.is_(None),
                    )
                )
                return result.scalar_one_or_none()

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

        conv_row, msg_rows = await asyncio.gather(_fetch_conversation(), _fetch_messages())

        if conv_row is None:
            return None

        conv_data = {k: v for k, v in conv_row.__dict__.items() if not k.startswith('_')}
        conv_data['messages'] = [
            {('timestamp' if k == 'created_at' else k): (v + timedelta(hours=7) if k == 'created_at' and v else v)
             for k, v in m.__dict__.items() if not k.startswith('_')}
            for m in msg_rows  # already DESC (newest first)
        ]
        return conv_data

    async def update_conversation(self, conversation_id: UUID, updates: Dict[str, Any]) -> bool:
        """Update conversation"""
        async with self.session_factory() as session:
            result = await session.execute(
                update(ConversationModel)
                .where(ConversationModel.id == str(conversation_id))
                .values(**updates)
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

    async def get_conversation_messages(self, conversation_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
        """Get messages for a conversation"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(MessageModel)
                .where(MessageModel.conversation_id == str(conversation_id))
                .order_by(MessageModel.created_at.asc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [row.__dict__ for row in rows]
