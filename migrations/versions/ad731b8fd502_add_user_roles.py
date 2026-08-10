"""add user roles and guest accounts

Revision ID: ad731b8fd502
Revises: 73d9c1f264aa
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad731b8fd502"
down_revision: Union[str, None] = "73d9c1f264aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), server_default="staff", nullable=False),
    )
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)
    op.create_check_constraint("ck_users_role", "users", "role IN ('guest', 'staff', 'admin')")


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE role = 'guest'")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)
    op.drop_column("users", "role")
