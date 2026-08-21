"""add sales return headers and product lines

Revision ID: c6d8e1f4a2b7
Revises: a93d7c5e124b
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c6d8e1f4a2b7"
down_revision: Union[str, None] = "a93d7c5e124b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_returns",
        sa.Column("return_id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(100), nullable=False, unique=True),
        sa.Column("return_number", sa.String(100), nullable=False, unique=True),
        sa.Column("returned_at", sa.DateTime(), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("customer_name_snapshot", sa.Text(), nullable=False),
        sa.Column("customer_address_detail_snapshot", sa.Text(), nullable=True),
        sa.Column("customer_village_name_snapshot", sa.String(), nullable=True),
        sa.Column("customer_ward_name_snapshot", sa.String(), nullable=True),
        sa.Column("return_total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("return_total_amount >= 0", name="ck_sales_returns_total_nonnegative"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"], ondelete="RESTRICT"),
        comment="Grain: one customer sales-return document (MDB reason NT).",
    )
    op.create_index("ix_sales_returns_returned_at", "sales_returns", ["returned_at"])
    op.create_index("ix_sales_returns_customer_id", "sales_returns", ["customer_id"])

    op.create_table(
        "sales_return_lines",
        sa.Column("return_line_id", sa.String(36), primary_key=True),
        sa.Column("return_id", sa.String(36), nullable=False),
        sa.Column("source_line_id", sa.String(100), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("product_category_name", sa.String(), nullable=True),
        sa.Column("unit_name", sa.String(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("line_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("line_number > 0", name="ck_sales_return_lines_line_number_positive"),
        sa.CheckConstraint("quantity >= 0", name="ck_sales_return_lines_quantity_nonnegative"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sales_return_lines_unit_price_nonnegative"),
        sa.CheckConstraint("line_amount >= 0", name="ck_sales_return_lines_amount_nonnegative"),
        sa.ForeignKeyConstraint(["return_id"], ["sales_returns.return_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("return_id", "source_line_id", name="uq_sales_return_lines_source"),
        sa.UniqueConstraint("return_id", "line_number", name="uq_sales_return_lines_line_number"),
        comment="Grain: one returned product line; subtract quantity and line_amount from sales.",
    )
    op.create_index("ix_sales_return_lines_return_id", "sales_return_lines", ["return_id"])
    op.create_index("ix_sales_return_lines_product_name", "sales_return_lines", ["product_name"])
    op.create_index("ix_sales_return_lines_category", "sales_return_lines", ["product_category_name"])


def downgrade() -> None:
    op.drop_table("sales_return_lines")
    op.drop_table("sales_returns")
