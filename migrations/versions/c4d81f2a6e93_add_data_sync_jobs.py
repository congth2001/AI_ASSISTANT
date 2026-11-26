"""add data_sync_jobs for syncs started from the admin screen

One row per sync started through ``POST /api/v1/data-sync/jobs``. A partial unique
index allows at most one ``running`` row, so two concurrent requests cannot start two
syncs. CLI/cron runs are not recorded here (their successful runs stay in
``etl_sync_runs``). The table is operational data: it is in RESTRICTED_SQL_TABLES and
``sales_sql_reader`` gets no privilege on it.

New table only; no existing data is touched.

Revision ID: c4d81f2a6e93
Revises: a91c3e7d5b20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4d81f2a6e93"
down_revision: Union[str, None] = "a91c3e7d5b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_sync_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("allow_shrink", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("triggered_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("source IN ('mdb', 'snapshot')", name="ck_data_sync_jobs_source"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_data_sync_jobs_status"
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_id"], ["users.id"],
            name="fk_data_sync_jobs_triggered_by_id", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Admin-triggered business-data syncs; at most one running row.",
    )
    op.create_index("ix_data_sync_jobs_created_at", "data_sync_jobs", ["created_at"])
    op.create_index(
        "uq_data_sync_jobs_single_running",
        "data_sync_jobs",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_data_sync_jobs_single_running", table_name="data_sync_jobs")
    op.drop_index("ix_data_sync_jobs_created_at", table_name="data_sync_jobs")
    op.drop_table("data_sync_jobs")
