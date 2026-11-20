"""add audit trail for retroactive debt-ledger changes between ETL runs

- etl_sync_runs: one row per successful business-data sync.
- customer_debt_transaction_changes: per-row updated/deleted/restored/backdated
  changes of customer_debt_transactions made by a run.
- customer_debt_revisions: per-customer summary of a run's retroactive changes.

New tables only; no existing data is touched. History starts at the first sync
after this migration (a baseline run records no changes).

Revision ID: 8008434c9371
Revises: e7b3c5a19f42
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8008434c9371"
down_revision: Union[str, None] = "e7b3c5a19f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etl_sync_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entrypoint", sa.String(length=64), nullable=False),
        sa.Column("allow_shrink", sa.Boolean(), nullable=False),
        sa.Column("debt_synced", sa.Boolean(), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("ledger_frontier_date", sa.Date(), nullable=True),
        sa.Column("debt_inserted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("debt_updated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("debt_deleted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("debt_restored", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("debt_backdated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
        comment="Audit: successful sales syncs; failed runs roll back and leave no row.",
    )
    op.create_index("ix_etl_sync_runs_started_at", "etl_sync_runs", ["started_at"])

    op.create_table(
        "customer_debt_transaction_changes",
        sa.Column("change_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("debt_transaction_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("previous_customer_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("change_type", sa.String(length=24), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("old_occurred_at", sa.DateTime(), nullable=True),
        sa.Column("new_occurred_at", sa.DateTime(), nullable=True),
        sa.Column("old_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("new_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("balance_delta", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint(
            "change_type IN ('updated', 'deleted', 'restored', 'backdated_insert')",
            name="ck_debt_changes_change_type",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["etl_sync_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["debt_transaction_id"],
            ["customer_debt_transactions.debt_transaction_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("change_id"),
        comment="Audit: per-row retroactive debt changes; balance_delta = new - old effective amount.",
    )
    op.create_index(
        "ix_debt_changes_customer_run", "customer_debt_transaction_changes", ["customer_id", "run_id"]
    )
    op.create_index("ix_debt_changes_run_id", "customer_debt_transaction_changes", ["run_id"])
    op.create_index(
        "ix_debt_changes_debt_transaction_id",
        "customer_debt_transaction_changes",
        ["debt_transaction_id"],
    )

    op.create_table(
        "customer_debt_revisions",
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("balance_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("balance_delta", sa.Numeric(18, 2), nullable=False),
        sa.Column("earliest_affected_at", sa.DateTime(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["etl_sync_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_id", "customer_id", name="pk_customer_debt_revisions"),
        comment="Audit: balance_before/after are whole-ledger balances; balance_delta is the retroactive part.",
    )
    op.create_index("ix_debt_revisions_customer_id", "customer_debt_revisions", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_debt_revisions_customer_id", table_name="customer_debt_revisions")
    op.drop_table("customer_debt_revisions")
    op.drop_index("ix_debt_changes_debt_transaction_id", table_name="customer_debt_transaction_changes")
    op.drop_index("ix_debt_changes_run_id", table_name="customer_debt_transaction_changes")
    op.drop_index("ix_debt_changes_customer_run", table_name="customer_debt_transaction_changes")
    op.drop_table("customer_debt_transaction_changes")
    op.drop_index("ix_etl_sync_runs_started_at", table_name="etl_sync_runs")
    op.drop_table("etl_sync_runs")
