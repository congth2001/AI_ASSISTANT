from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from src.domain.interfaces.i_conversation_repository import IConversationRepository
from src.infrastructure.persistence.models import ConversationModel, MessageModel

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
                extra_metadata=conversation_data.get('metadata')
            )
            session.add(conversation)
            await session.commit()
            return conversation.__dict__

    async def get_conversation(self, conversation_id: UUID) -> Optional[Dict[str, Any]]:
        """Get conversation by ID"""
        async with self.session_factory() as session:
            result = await session.execute(
                ConversationModel.__table__.select().where(
                    ConversationModel.id == str(conversation_id)
                )
            )
            row = result.first()
            if row:
                return dict(row._mapping)
            return None

    async def update_conversation(self, conversation_id: UUID, updates: Dict[str, Any]) -> bool:
        """Update conversation"""
        async with self.session_factory() as session:
            result = await session.execute(
                ConversationModel.__table__.update()
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
                timestamp=message_data.get('timestamp'),
                extra_metadata=message_data.get('metadata')
            )
            session.add(message)
            await session.commit()
            return True

    async def get_conversation_messages(self, conversation_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
        """Get messages for a conversation"""
        async with self.session_factory() as session:
            result = await session.execute(
                MessageModel.__table__.select()
                .where(MessageModel.conversation_id == str(conversation_id))
                .order_by(MessageModel.timestamp.desc())
                .limit(limit)
            )
            rows = result.all()
            return [dict(row._mapping) for row in rows]
