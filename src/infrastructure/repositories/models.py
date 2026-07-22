from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, relationship


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


class Customer(Base):
    """Canonical customer identity used across sales invoices."""

    __tablename__ = "customers"

    customer_id = Column(
        postgresql.UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    customer_identity_key = Column(Text, nullable=False)
    customer_name = Column(Text, nullable=False)
    address_detail = Column(Text, nullable=True)
    village_name = Column(String, nullable=True)
    ward_name = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    invoices = relationship("SalesInvoice", back_populates="customer")

    __table_args__ = (
        Index("ix_customers_customer_name", "customer_name"),
        UniqueConstraint(
            "customer_identity_key",
            name="uq_customers_customer_identity_key",
        ),
    )


class SalesInvoice(Base):
    """One row per sales invoice."""

    __tablename__ = "sales_invoices"

    invoice_id = Column(String, primary_key=True)
    invoice_number = Column(String, nullable=False)
    issued_at = Column(DateTime, nullable=False)
    customer_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey(
            "customers.customer_id",
            name="fk_sales_invoices_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    customer_name_snapshot = Column(Text, nullable=False)
    customer_address_detail_snapshot = Column(Text, nullable=True)
    customer_village_name_snapshot = Column(String, nullable=True)
    customer_ward_name_snapshot = Column(String, nullable=True)
    invoice_total_amount = Column(Numeric(18, 2), nullable=False)
    debt_delta_amount = Column(Numeric(18, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="invoices")
    lines = relationship("SalesInvoiceLine", back_populates="invoice")

    __table_args__ = (
        Index(
            "ux_sales_invoices_invoice_number",
            "invoice_number",
            unique=True,
        ),
        Index("ix_sales_invoices_issued_at", "issued_at"),
        Index("ix_sales_invoices_customer_id", "customer_id"),
        CheckConstraint(
            "invoice_total_amount >= 0",
            name="ck_sales_invoices_total_nonnegative",
        ),
    )


class SalesInvoiceLine(Base):
    """One row per line item inside a sales invoice."""

    __tablename__ = "sales_invoice_lines"

    invoice_line_id = Column(String, primary_key=True)
    invoice_id = Column(
        String,
        ForeignKey(
            "sales_invoices.invoice_id",
            name="fk_sales_invoice_lines_invoice_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    line_number = Column(Integer, nullable=False)
    product_name = Column(Text, nullable=False)
    product_category_name = Column(String, nullable=True)
    unit_name = Column(String, nullable=False)
    unit_price = Column(Numeric(18, 2), nullable=False)
    quantity = Column(Numeric(18, 3), nullable=False)
    line_amount = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    invoice = relationship("SalesInvoice", back_populates="lines")

    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "line_number",
            name="uq_sales_invoice_lines_invoice_line",
        ),
        Index("ix_sales_invoice_lines_invoice_id", "invoice_id"),
        Index("ix_sales_invoice_lines_product_name", "product_name"),
        Index(
            "ix_sales_invoice_lines_product_category_name",
            "product_category_name",
        ),
        CheckConstraint(
            "line_number > 0",
            name="ck_sales_invoice_lines_line_number_positive",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_sales_invoice_lines_quantity_nonnegative",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_sales_invoice_lines_unit_price_nonnegative",
        ),
        CheckConstraint(
            "line_amount >= 0",
            name="ck_sales_invoice_lines_amount_nonnegative",
        ),
    )
