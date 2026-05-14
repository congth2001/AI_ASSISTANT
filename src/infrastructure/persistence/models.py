from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, DateTime, Text, Float, JSON
from datetime import datetime


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
    extra_metadata = Column("metadata", JSON, nullable=True)


class MessageModel(Base):
    """SQLAlchemy model for messages"""
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    conversation_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    timestamp = Column(DateTime, default=datetime.utcnow)
    extra_metadata = Column("metadata", JSON, nullable=True)


class BusinessDataModel(Base):
    """SQLAlchemy model for business data"""
    __tablename__ = "business_data"

    id = Column(String, primary_key=True)
    data_type = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    date = Column(DateTime, nullable=False)
    category = Column(String, nullable=True)
    subcategory = Column(String, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
