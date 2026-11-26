"""add hot-path indexes and drop redundant ones

- messages: composite index serving "messages of a conversation, in order".
- customer_debt_transactions: (customer_id, occurred_at) for per-customer
  balances/ledger ranges; its customer_id prefix makes ix_debt_transactions_customer_id
  redundant, so that index is replaced.
- sales_invoices.ix_sales_invoices_issued_at: every query filters
  deleted_at IS NULL and uses the partial ix_sales_invoices_active_issued_at.
- sales_invoice_lines.ix_sales_invoice_lines_invoice_id and
  sales_return_lines.ix_sales_return_lines_return_id: duplicate the leading column
  of the (invoice_id|return_id, ...) unique constraints.

Plain CREATE INDEX is used (transactional DDL); the affected tables are small
enough that the brief write lock is acceptable. For a very large messages table,
create the index manually with CREATE INDEX CONCURRENTLY first.

Revision ID: e7b3c5a19f42
Revises: d1e5b7a93c28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7b3c5a19f42"
down_revision: Union[str, None] = "d1e5b7a93c28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_conversation_id_created_at",
        "messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_debt_transactions_customer_occurred",
        "customer_debt_transactions",
        ["customer_id", "occurred_at"],
    )
    op.drop_index("ix_debt_transactions_customer_id", table_name="customer_debt_transactions")
    op.drop_index("ix_sales_invoices_issued_at", table_name="sales_invoices")
    op.drop_index("ix_sales_invoice_lines_invoice_id", table_name="sales_invoice_lines")
    op.drop_index("ix_sales_return_lines_return_id", table_name="sales_return_lines")


def downgrade() -> None:
    op.create_index("ix_sales_return_lines_return_id", "sales_return_lines", ["return_id"])
    op.create_index("ix_sales_invoice_lines_invoice_id", "sales_invoice_lines", ["invoice_id"])
    op.create_index("ix_sales_invoices_issued_at", "sales_invoices", ["issued_at"])
    op.create_index(
        "ix_debt_transactions_customer_id", "customer_debt_transactions", ["customer_id"]
    )
    op.drop_index(
        "ix_debt_transactions_customer_occurred", table_name="customer_debt_transactions"
    )
    op.drop_index("ix_messages_conversation_id_created_at", table_name="messages")
