from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, DateTime, Text, Float, JSON, ForeignKey, Index
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
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    deleted_at = Column(DateTime, nullable=True)


class MessageModel(Base):
    """SQLAlchemy model for messages"""
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    conversation_id = Column(ForeignKey("conversations.id"), nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

class InvoiceCustomer(Base):
    """SQLAlchemy model for invoice customers"""
    __tablename__ = "invoice_customers"

    id = Column(String, primary_key=True)
    invoice_id = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    name = Column(String, nullable=False)
    address_detail = Column(String, nullable=True)
    address_village = Column(String, nullable=True)
    address_ward = Column(String, nullable=True)
    total_amount = Column(Float, nullable=False)
    debt_amount = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('invoice_customers_invoice_id_idx', 'invoice_id', unique=True),
    )

class InvoiceGood(Base):
    """SQLAlchemy model for invoice goods"""
    __tablename__ = "invoice_goods"

    id = Column(String, primary_key=True)
    invoice_id = Column(String, ForeignKey("invoice_customers.invoice_id"), nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    unit_type = Column(String, nullable=False)
    unit_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)
