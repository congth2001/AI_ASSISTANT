from datetime import datetime, timezone

from sqlalchemy import (
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
from sqlalchemy.orm import relationship

from src.common.infrastructure.database.base import Base


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
        Index(
            "ix_customers_active_ward_name",
            "ward_name",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_customers_active_village_name",
            "village_name",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        UniqueConstraint(
            "customer_identity_key",
            name="uq_customers_customer_identity_key",
        ),
        {
            "comment": (
                "Grain: one row per provisional customer identity. "
                "customer_id is the stable UUID; customer_identity_key is "
                "normalized name + ward + village until a source customer "
                "code exists."
            )
        },
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
        comment=(
            "Stable UUID foreign key to customers; use this column instead "
            "of grouping by customer_name_snapshot."
        ),
    )
    customer_name_snapshot = Column(Text, nullable=False)
    customer_address_detail_snapshot = Column(Text, nullable=True)
    customer_village_name_snapshot = Column(String, nullable=True)
    customer_ward_name_snapshot = Column(String, nullable=True)
    invoice_total_amount = Column(
        Numeric(18, 2),
        nullable=False,
        comment=(
            "Authoritative invoice-level total; it is not guaranteed to "
            "equal SUM(sales_invoice_lines.line_amount) until source "
            "reconciliation is complete."
        ),
    )
    debt_delta_amount = Column(
        Numeric(18, 2),
        nullable=True,
        comment=(
            "Signed debt movement recorded by this invoice: positive "
            "increases receivable, negative represents advance/credit."
        ),
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    customer = relationship("Customer", back_populates="invoices")
    lines = relationship("SalesInvoiceLine", back_populates="invoice")

    __table_args__ = (
        Index(
            "ux_sales_invoices_invoice_number",
            "invoice_number",
            unique=True,
        ),
        Index("ix_sales_invoices_issued_at", "issued_at"),
        Index(
            "ix_sales_invoices_active_issued_at",
            "issued_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_sales_invoices_customer_id", "customer_id"),
        CheckConstraint(
            "invoice_total_amount >= 0",
            name="ck_sales_invoices_total_nonnegative",
        ),
        {
            "comment": (
                "Grain: one row per sales invoice. Join customers by "
                "customer_id; snapshot columns preserve the customer text "
                "printed on the historical invoice."
            )
        },
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
    line_number = Column(
        Integer,
        nullable=False,
        comment=(
            "Stable ordinal of the source line within its invoice; unique "
            "together with invoice_id."
        ),
    )
    product_name = Column(Text, nullable=False)
    product_category_name = Column(String, nullable=True)
    unit_name = Column(String, nullable=False)
    unit_price = Column(Numeric(18, 2), nullable=False)
    quantity = Column(Numeric(18, 3), nullable=False)
    line_amount = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

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
        {
            "comment": (
                "Grain: one row per line item within a sales invoice. Use "
                "line_amount for product/category revenue."
            )
        },
    )


class SalesReturn(Base):
    """One row per customer sales-return document from iShopman."""

    __tablename__ = "sales_returns"

    return_id = Column(String(36), primary_key=True)
    source_id = Column(String(100), nullable=False, unique=True)
    return_number = Column(String(100), nullable=False, unique=True)
    returned_at = Column(DateTime, nullable=False)
    customer_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey("customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_name_snapshot = Column(Text, nullable=False)
    customer_address_detail_snapshot = Column(Text, nullable=True)
    customer_village_name_snapshot = Column(String, nullable=True)
    customer_ward_name_snapshot = Column(String, nullable=True)
    return_total_amount = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    lines = relationship("SalesReturnLine", back_populates="sales_return")

    __table_args__ = (
        Index("ix_sales_returns_returned_at", "returned_at"),
        Index("ix_sales_returns_customer_id", "customer_id"),
        CheckConstraint("return_total_amount >= 0", name="ck_sales_returns_total_nonnegative"),
        {"comment": "Grain: one customer sales-return document (MDB reason NT)."},
    )


class SalesReturnLine(Base):
    """One returned product line within a sales-return document."""

    __tablename__ = "sales_return_lines"

    return_line_id = Column(String(36), primary_key=True)
    return_id = Column(
        String(36),
        ForeignKey("sales_returns.return_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_line_id = Column(String(100), nullable=False)
    line_number = Column(Integer, nullable=False)
    product_name = Column(Text, nullable=False)
    product_category_name = Column(String, nullable=True)
    unit_name = Column(String, nullable=False)
    unit_price = Column(Numeric(18, 2), nullable=False)
    quantity = Column(Numeric(18, 3), nullable=False)
    line_amount = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    sales_return = relationship("SalesReturn", back_populates="lines")

    __table_args__ = (
        UniqueConstraint("return_id", "source_line_id", name="uq_sales_return_lines_source"),
        UniqueConstraint("return_id", "line_number", name="uq_sales_return_lines_line_number"),
        Index("ix_sales_return_lines_return_id", "return_id"),
        Index("ix_sales_return_lines_product_name", "product_name"),
        Index("ix_sales_return_lines_category", "product_category_name"),
        CheckConstraint("line_number > 0", name="ck_sales_return_lines_line_number_positive"),
        CheckConstraint("quantity >= 0", name="ck_sales_return_lines_quantity_nonnegative"),
        CheckConstraint("unit_price >= 0", name="ck_sales_return_lines_unit_price_nonnegative"),
        CheckConstraint("line_amount >= 0", name="ck_sales_return_lines_amount_nonnegative"),
        {"comment": "Grain: one returned product line; subtract quantity and line_amount from sales."},
    )


class CustomerDebtTransaction(Base):
    """Signed customer receivable ledger entry from the source system."""

    __tablename__ = "customer_debt_transactions"

    debt_transaction_id = Column(String(36), primary_key=True)
    customer_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey("customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(100), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_debt_transactions_source"),
        Index("ix_debt_transactions_customer_id", "customer_id"),
        Index("ix_debt_transactions_occurred_at", "occurred_at"),
        CheckConstraint(
            "source_type IN ('opening', 'sale', 'receipt', 'sales_return')",
            name="ck_debt_transactions_source_type",
        ),
        {"comment": "Signed receivable ledger: positive increases debt; negative decreases debt."},
    )
