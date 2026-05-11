from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, JSON
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
import json

from src.domain.interfaces.i_data_repository import IDataRepository
from src.domain.interfaces.i_conversation_repository import IConversationRepository


class Base(DeclarativeBase):
    """SQLAlchemy base class"""
    pass


class ConversationModel(Base):
    """SQLAlchemy model for conversations"""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    metadata = Column(JSON, nullable=True)


class MessageModel(Base):
    """SQLAlchemy model for messages"""
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    conversation_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    timestamp = Column(DateTime, default=datetime.utcnow)
    metadata = Column(JSON, nullable=True)


class BusinessDataModel(Base):
    """SQLAlchemy model for business data"""
    __tablename__ = "business_data"

    id = Column(String, primary_key=True)
    data_type = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    date = Column(DateTime, nullable=False)
    category = Column(String, nullable=True)
    subcategory = Column(String, nullable=True)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationRepository(IConversationRepository):
    """SQLAlchemy implementation of conversation repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new conversation"""
        async with self.session_factory() as session:
            conversation = ConversationModel(
                id=conversation_data['id'],
                user_id=conversation_data.get('user_id'),
                title=conversation_data.get('title'),
                metadata=conversation_data.get('metadata')
            )
            session.add(conversation)
            await session.commit()
            return conversation_data

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
                metadata=message_data.get('metadata')
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


class BusinessDataRepository(IDataRepository):
    """SQLAlchemy implementation of business data repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_business_data(self, data_type: str, date_range: Optional['DateRange'] = None) -> List[Dict[str, Any]]:
        """Get business data by type and date range"""
        async with self.session_factory() as session:
            query = BusinessDataModel.__table__.select().where(
                BusinessDataModel.data_type == data_type
            )

            if date_range:
                query = query.where(
                    BusinessDataModel.date >= date_range.start_date,
                    BusinessDataModel.date <= date_range.end_date
                )

            result = await session.execute(query)
            rows = result.all()
            return [dict(row._mapping) for row in rows]

    async def store_business_data(self, data: Dict[str, Any]) -> bool:
        """Store business data"""
        async with self.session_factory() as session:
            business_data = BusinessDataModel(
                id=data['id'],
                data_type=data['data_type'],
                value=data['value'],
                date=data['date'],
                category=data.get('category'),
                subcategory=data.get('subcategory'),
                metadata=data.get('metadata')
            )
            session.add(business_data)
            await session.commit()
            return True

    async def get_customers(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get customer data with optional filters"""
        # Note: This is a simplified implementation
        # In a real system, you'd have a separate CustomerModel
        async with self.session_factory() as session:
            query = BusinessDataModel.__table__.select().where(
                BusinessDataModel.data_type == 'customer'
            )

            if filters:
                if 'segment' in filters:
                    # This would require a proper customer table
                    pass

            result = await session.execute(query)
            rows = result.all()
            return [dict(row._mapping) for row in rows]