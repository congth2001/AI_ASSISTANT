"""create legacy baseline schema

Revision ID: 1a6f3c8d2e90
Revises:

The project originally created these tables with ``Base.metadata.create_all``
before Alembic was introduced.  Later revisions therefore assumed that the
tables already existed, which made ``alembic upgrade head`` fail on an empty
database.  This baseline records that pre-Alembic schema explicitly.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a6f3c8d2e90"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "invoice_customers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address_detail", sa.String(), nullable=True),
        sa.Column("address_village", sa.String(), nullable=True),
        sa.Column("address_ward", sa.String(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("debt_amount", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "invoice_customers_invoice_id_idx",
        "invoice_customers",
        ["invoice_id"],
        unique=True,
    )
    op.create_table(
        "invoice_goods",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("unit_type", sa.String(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("total_price", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoice_customers.invoice_id"],
            name="invoice_goods_invoice_customers_fk",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("invoice_goods")
    op.drop_index(
        "invoice_customers_invoice_id_idx",
        table_name="invoice_customers",
    )
    op.drop_table("invoice_customers")
    op.drop_table("messages")
    op.drop_table("conversations")
