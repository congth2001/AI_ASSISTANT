"""make chat timestamps timezone aware

Revision ID: f2b86c913e41
Revises: ad731b8fd502
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b86c913e41"
down_revision: Union[str, None] = "ad731b8fd502"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _upgrade_timestamp(table: str, column: str) -> None:
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(timezone=False),
        type_=sa.DateTime(timezone=True),
        postgresql_using=f"{column} AT TIME ZONE 'UTC'",
    )


def _downgrade_timestamp(table: str, column: str) -> None:
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(timezone=False),
        postgresql_using=f"{column} AT TIME ZONE 'UTC'",
    )


def upgrade() -> None:
    for table in ("conversations", "messages"):
        for column in ("created_at", "updated_at", "deleted_at"):
            _upgrade_timestamp(table, column)

    op.alter_column(
        "conversations",
        "created_at",
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "conversations",
        "updated_at",
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "messages",
        "created_at",
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    op.alter_column("messages", "created_at", server_default=None)
    op.alter_column("conversations", "updated_at", server_default=None)
    op.alter_column("conversations", "created_at", server_default=None)

    for table in ("messages", "conversations"):
        for column in ("created_at", "updated_at", "deleted_at"):
            _downgrade_timestamp(table, column)
