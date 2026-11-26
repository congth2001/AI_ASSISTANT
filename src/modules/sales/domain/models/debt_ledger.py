"""Debt-ledger rows and the audit trail of retroactive changes between ETL runs.

See ``docs/customer-debt-history.md`` (section 3.3 and 4) for the business rules.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class DebtChangeType(str, Enum):
    UPDATED = "updated"
    DELETED = "deleted"
    RESTORED = "restored"
    BACKDATED_INSERT = "backdated_insert"


@dataclass(frozen=True)
class IncomingDebtRow:
    """One validated row of the source snapshot, already resolved to a customer."""

    source_type: str
    source_id: str
    customer_id: str
    occurred_at: datetime
    amount: Decimal

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_type, self.source_id)


@dataclass(frozen=True)
class DebtLedgerRow:
    """Stored ledger row, including soft-deleted ones (``deleted=True``)."""

    debt_transaction_id: str
    source_type: str
    source_id: str
    customer_id: str
    occurred_at: datetime
    amount: Decimal
    deleted: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_type, self.source_id)


@dataclass(frozen=True)
class DebtTransactionChange:
    """How one ledger row changed in a run.

    ``customer_id`` is the customer after the change (before it for ``deleted``);
    ``previous_customer_id`` is set only when the row moved to another customer.
    ``balance_delta`` is new effective amount minus old effective amount, where a
    deleted row counts as 0. For ``restored`` the ``old_*`` values are the ones the
    row had when it was deleted, shown for context only.
    """

    debt_transaction_id: str
    change_type: DebtChangeType
    source_type: str
    source_id: str
    customer_id: str
    previous_customer_id: str | None
    old_occurred_at: datetime | None
    new_occurred_at: datetime | None
    old_amount: Decimal | None
    new_amount: Decimal | None
    balance_delta: Decimal


@dataclass(frozen=True)
class CustomerDebtRevision:
    """Per-customer summary of a run that changed that customer's past ledger.

    ``balance_before``/``balance_after`` are whole-ledger balances right before and
    after the run, so they also include ordinary new entries; ``balance_delta`` is only
    the part caused by retroactive changes.
    """

    customer_id: str
    balance_before: Decimal
    balance_after: Decimal
    balance_delta: Decimal
    earliest_affected_at: datetime
    change_count: int


@dataclass(frozen=True)
class DebtSnapshotDiff:
    """Everything needed to apply a snapshot and record its audit trail.

    ``inserts`` carry freshly assigned ids; ``updates`` and ``restores`` keep the
    stored id; ``deletes`` are ids to soft delete. Unchanged rows are not rewritten.
    On a baseline run (no active ledger before the run) ``changes`` and
    ``revisions`` are empty because there is nothing to compare against.
    """

    inserts: tuple[DebtLedgerRow, ...] = field(default_factory=tuple)
    updates: tuple[DebtLedgerRow, ...] = field(default_factory=tuple)
    restores: tuple[DebtLedgerRow, ...] = field(default_factory=tuple)
    deletes: tuple[str, ...] = field(default_factory=tuple)
    unchanged: int = 0
    changes: tuple[DebtTransactionChange, ...] = field(default_factory=tuple)
    revisions: tuple[CustomerDebtRevision, ...] = field(default_factory=tuple)
    frontier_date: date | None = None
    is_baseline: bool = False

    @property
    def backdated_count(self) -> int:
        return sum(1 for c in self.changes if c.change_type is DebtChangeType.BACKDATED_INSERT)

    @property
    def retroactive_delta(self) -> Decimal:
        return sum((r.balance_delta for r in self.revisions), Decimal("0"))


@dataclass(frozen=True)
class EtlSyncRun:
    """One successful ``sync_all`` call; persisted in the same transaction as its writes."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    entrypoint: str
    allow_shrink: bool
    debt_synced: bool
    is_baseline: bool
    ledger_frontier_date: date | None
    debt_inserted: int = 0
    debt_updated: int = 0
    debt_deleted: int = 0
    debt_restored: int = 0
    debt_backdated: int = 0
