"""add customer debt transaction ledger

Revision ID: e8c1a4d92f30
Revises: d7a4c92e8f10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e8c1a4d92f30"
down_revision: Union[str, None] = "d7a4c92e8f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_debt_transactions",
        sa.Column("debt_transaction_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('opening', 'sale', 'receipt', 'sales_return')",
            name="ck_debt_transactions_source_type",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("debt_transaction_id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_debt_transactions_source"),
        comment="Signed receivable ledger: positive increases debt; negative decreases debt.",
    )
    op.create_index("ix_debt_transactions_customer_id", "customer_debt_transactions", ["customer_id"])
    op.create_index("ix_debt_transactions_occurred_at", "customer_debt_transactions", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_debt_transactions_occurred_at", table_name="customer_debt_transactions")
    op.drop_index("ix_debt_transactions_customer_id", table_name="customer_debt_transactions")
    op.drop_table("customer_debt_transactions")
