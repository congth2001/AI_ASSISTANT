from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
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
    # Deliberately timezone-naive: the source (iShopman) stores Vietnam local
    # wall-clock time, and reports bucket/filter by that local date. Do not
    # convert to timestamptz without a data migration that interprets values
    # as Asia/Ho_Chi_Minh (see docs/data-model.md, "Múi giờ và kiểu thời gian").
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
        # Every read filters deleted_at IS NULL, so only the partial index is kept;
        # the former full ix_sales_invoices_issued_at was dropped as redundant.
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
        # invoice_id lookups use the (invoice_id, line_number) unique constraint above.
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
    # Naive Vietnam local time by design (same convention as sales_invoices.issued_at).
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
        # return_id lookups use uq_sales_return_lines_source / uq_sales_return_lines_line_number.
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
    # Naive Vietnam local time by design (same convention as sales_invoices.issued_at).
    occurred_at = Column(DateTime, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_debt_transactions_source"),
        # Serves per-customer balances and ledger ranges; its customer_id prefix also
        # covers the RESTRICT foreign key (replaces ix_debt_transactions_customer_id).
        Index("ix_debt_transactions_customer_occurred", "customer_id", "occurred_at"),
        Index("ix_debt_transactions_occurred_at", "occurred_at"),
        CheckConstraint(
            "source_type IN ('opening', 'sale', 'receipt', 'sales_return')",
            name="ck_debt_transactions_source_type",
        ),
        {"comment": "Signed receivable ledger: positive increases debt; negative decreases debt."},
    )


DEBT_CHANGE_TYPES = ("updated", "deleted", "restored", "backdated_insert")


class EtlSyncRun(Base):
    """One successful business-data sync; written in the same transaction as its data."""

    __tablename__ = "etl_sync_runs"

    run_id = Column(postgresql.UUID(as_uuid=False), primary_key=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False)
    entrypoint = Column(String(64), nullable=False)
    allow_shrink = Column(Boolean, nullable=False)
    debt_synced = Column(Boolean, nullable=False)
    is_baseline = Column(Boolean, nullable=False)
    # Latest transaction date of the active ledger before the run (Vietnam local date).
    ledger_frontier_date = Column(Date, nullable=True)
    debt_inserted = Column(Integer, nullable=False, server_default=text("0"))
    debt_updated = Column(Integer, nullable=False, server_default=text("0"))
    debt_deleted = Column(Integer, nullable=False, server_default=text("0"))
    debt_restored = Column(Integer, nullable=False, server_default=text("0"))
    debt_backdated = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("ix_etl_sync_runs_started_at", "started_at"),
        {"comment": "Audit: successful sales syncs; failed runs roll back and leave no row."},
    )


class CustomerDebtTransactionChange(Base):
    """Retroactive change to one debt-ledger row made by an ETL run."""

    __tablename__ = "customer_debt_transaction_changes"

    change_id = Column(BigInteger, Identity(always=False), primary_key=True)
    run_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey("etl_sync_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    debt_transaction_id = Column(
        String(36),
        ForeignKey("customer_debt_transactions.debt_transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey("customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_customer_id = Column(postgresql.UUID(as_uuid=False), nullable=True)
    change_type = Column(String(24), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(100), nullable=False)
    # Naive Vietnam local time, same convention as customer_debt_transactions.occurred_at.
    old_occurred_at = Column(DateTime, nullable=True)
    new_occurred_at = Column(DateTime, nullable=True)
    old_amount = Column(Numeric(18, 2), nullable=True)
    new_amount = Column(Numeric(18, 2), nullable=True)
    balance_delta = Column(Numeric(18, 2), nullable=False)

    __table_args__ = (
        Index("ix_debt_changes_customer_run", "customer_id", "run_id"),
        Index("ix_debt_changes_run_id", "run_id"),
        Index("ix_debt_changes_debt_transaction_id", "debt_transaction_id"),
        CheckConstraint(
            "change_type IN ('updated', 'deleted', 'restored', 'backdated_insert')",
            name="ck_debt_changes_change_type",
        ),
        {"comment": "Audit: per-row retroactive debt changes; balance_delta = new - old effective amount."},
    )


class CustomerDebtRevision(Base):
    """Per-customer summary of the retroactive debt changes of one ETL run."""

    __tablename__ = "customer_debt_revisions"

    run_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey("etl_sync_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id = Column(
        postgresql.UUID(as_uuid=False),
        ForeignKey("customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    balance_before = Column(Numeric(18, 2), nullable=False)
    balance_after = Column(Numeric(18, 2), nullable=False)
    balance_delta = Column(Numeric(18, 2), nullable=False)
    earliest_affected_at = Column(DateTime, nullable=False)
    change_count = Column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("run_id", "customer_id", name="pk_customer_debt_revisions"),
        Index("ix_debt_revisions_customer_id", "customer_id"),
        {"comment": "Audit: balance_before/after are whole-ledger balances; balance_delta is the retroactive part."},
    )
