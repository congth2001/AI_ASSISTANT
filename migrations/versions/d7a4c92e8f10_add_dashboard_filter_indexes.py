"""add dashboard filter indexes

Revision ID: d7a4c92e8f10
Revises: b4e2a7c91d63
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7a4c92e8f10"
down_revision: Union[str, None] = "b4e2a7c91d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_customers_active_ward_name",
        "customers",
        ["ward_name"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_customers_active_village_name",
        "customers",
        ["village_name"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_sales_invoices_active_issued_at",
        "sales_invoices",
        ["issued_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sales_invoices_active_issued_at",
        table_name="sales_invoices",
    )
    op.drop_index(
        "ix_customers_active_village_name",
        table_name="customers",
    )
    op.drop_index(
        "ix_customers_active_ward_name",
        table_name="customers",
    )
