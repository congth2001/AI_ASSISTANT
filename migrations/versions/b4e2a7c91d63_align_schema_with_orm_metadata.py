"""align schema with ORM metadata

Revision ID: b4e2a7c91d63
Revises: f2b86c913e41
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e2a7c91d63"
down_revision: Union[str, None] = "f2b86c913e41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "sales_invoices",
        "customer_name_snapshot",
        existing_type=sa.String(),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoices",
        "customer_address_detail_snapshot",
        existing_type=sa.String(),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoice_lines",
        "product_name",
        existing_type=sa.String(),
        type_=sa.Text(),
        existing_nullable=False,
    )

    # ``ix_users_email`` already enforces uniqueness. Keeping both objects
    # causes schema drift and performs the same check twice on every write.
    op.drop_constraint("uq_users_email", "users", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.alter_column(
        "sales_invoice_lines",
        "product_name",
        existing_type=sa.Text(),
        type_=sa.String(),
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoices",
        "customer_address_detail_snapshot",
        existing_type=sa.Text(),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoices",
        "customer_name_snapshot",
        existing_type=sa.Text(),
        type_=sa.String(),
        existing_nullable=False,
    )
