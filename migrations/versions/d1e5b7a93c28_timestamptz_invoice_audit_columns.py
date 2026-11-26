"""make invoice audit timestamps timezone-aware

sales_invoices / sales_invoice_lines stored created_at and deleted_at as naive
timestamps written with datetime.utcnow(), so existing values are UTC.
Business-time columns (issued_at, returned_at, occurred_at) stay naive local time.

Revision ID: d1e5b7a93c28
Revises: c6d8e1f4a2b7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1e5b7a93c28"
down_revision: Union[str, None] = "c6d8e1f4a2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("sales_invoices", "created_at"),
    ("sales_invoices", "deleted_at"),
    ("sales_invoice_lines", "created_at"),
    ("sales_invoice_lines", "deleted_at"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
