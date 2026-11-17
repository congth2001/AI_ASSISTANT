from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text, text

from src.common.infrastructure.database.base import Base


class ConversationModel(Base):
    """SQLAlchemy model for conversations"""

    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    user_id = Column(
        String(36),
        ForeignKey("users.id", name="fk_conversations_user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title = Column(String, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=True,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class MessageModel(Base):
    """SQLAlchemy model for messages"""

    __tablename__ = "messages"
    __table_args__ = (
        # Serves "messages of a conversation, newest first". The matching Alembic migration
        # (index `ix_messages_conversation_id_created_at`) is created separately.
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id = Column(String, primary_key=True)
    conversation_id = Column(ForeignKey("conversations.id"), nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


