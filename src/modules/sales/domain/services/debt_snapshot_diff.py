"""Compare a full debt-ledger snapshot with the stored ledger (pure, no I/O).

Rules (``docs/customer-debt-history.md`` section 3.3):

* rows are matched by ``(source_type, source_id)``;
* an active row whose customer, ``occurred_at`` or amount differs is ``updated``;
* an active row missing from the snapshot is ``deleted`` (soft delete);
* a soft-deleted row present again is ``restored``;
* a new row dated before the *frontier* (latest transaction date of the active
  ledger before the run) is a ``backdated_insert``; new rows on or after the
  frontier are ordinary activity and are not part of the audit trail;
* with no active ledger before the run (baseline) nothing is recorded.

Amounts compare at cent precision; timestamps compare exactly.
"""
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from src.modules.sales.domain.errors import DuplicateDebtTransactionsError
from src.modules.sales.domain.models.debt_ledger import (
    CustomerDebtRevision,
    DebtChangeType,
    DebtLedgerRow,
    DebtSnapshotDiff,
    DebtTransactionChange,
    IncomingDebtRow,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _new_id() -> str:
    return str(uuid4())


def _same_values(stored: DebtLedgerRow, row: IncomingDebtRow) -> bool:
    return (
        stored.customer_id == row.customer_id
        and stored.occurred_at == row.occurred_at
        and _money(stored.amount) == _money(row.amount)
    )


def _written(row: IncomingDebtRow, debt_transaction_id: str) -> DebtLedgerRow:
    return DebtLedgerRow(
        debt_transaction_id=debt_transaction_id,
        source_type=row.source_type,
        source_id=row.source_id,
        customer_id=row.customer_id,
        occurred_at=row.occurred_at,
        amount=_money(row.amount),
    )


def _change(
    change_type: DebtChangeType,
    *,
    old: DebtLedgerRow | None,
    new: DebtLedgerRow | None,
) -> DebtTransactionChange:
    reference = new or old
    assert reference is not None
    old_effective = ZERO if old is None or old.deleted else _money(old.amount)
    new_effective = ZERO if new is None else _money(new.amount)
    previous_customer = (
        old.customer_id
        if old is not None and new is not None and old.customer_id != new.customer_id
        else None
    )
    return DebtTransactionChange(
        debt_transaction_id=reference.debt_transaction_id,
        change_type=change_type,
        source_type=reference.source_type,
        source_id=reference.source_id,
        customer_id=reference.customer_id,
        previous_customer_id=previous_customer,
        old_occurred_at=old.occurred_at if old is not None else None,
        new_occurred_at=new.occurred_at if new is not None else None,
        old_amount=_money(old.amount) if old is not None else None,
        new_amount=_money(new.amount) if new is not None else None,
        balance_delta=new_effective - old_effective,
    )


def _customer_impacts(
    change: DebtTransactionChange,
) -> list[tuple[str, Decimal, datetime]]:
    """Split one change into ``(customer_id, balance delta, affected time)`` parts."""
    old_amount = change.old_amount or ZERO
    new_amount = change.new_amount or ZERO
    if change.change_type is DebtChangeType.DELETED:
        assert change.old_occurred_at is not None
        return [(change.customer_id, -old_amount, change.old_occurred_at)]
    assert change.new_occurred_at is not None
    if change.change_type is not DebtChangeType.UPDATED:
        # Restored or backdated insert: the old state (if any) did not count.
        return [(change.customer_id, new_amount, change.new_occurred_at)]
    assert change.old_occurred_at is not None
    if change.previous_customer_id is not None:
        return [
            (change.previous_customer_id, -old_amount, change.old_occurred_at),
            (change.customer_id, new_amount, change.new_occurred_at),
        ]
    return [(
        change.customer_id,
        new_amount - old_amount,
        min(change.old_occurred_at, change.new_occurred_at),
    )]


def _revisions(
    changes: list[DebtTransactionChange],
    balance_before: dict[str, Decimal],
    balance_after: dict[str, Decimal],
) -> tuple[CustomerDebtRevision, ...]:
    delta: dict[str, Decimal] = defaultdict(lambda: ZERO)
    earliest: dict[str, datetime] = {}
    counts: dict[str, int] = defaultdict(int)
    for change in changes:
        for customer_id, amount, affected_at in _customer_impacts(change):
            delta[customer_id] += amount
            counts[customer_id] += 1
            if customer_id not in earliest or affected_at < earliest[customer_id]:
                earliest[customer_id] = affected_at
    return tuple(
        CustomerDebtRevision(
            customer_id=customer_id,
            balance_before=balance_before.get(customer_id, ZERO),
            balance_after=balance_after.get(customer_id, ZERO),
            balance_delta=delta[customer_id],
            earliest_affected_at=earliest[customer_id],
            change_count=counts[customer_id],
        )
        for customer_id in sorted(counts)
    )


def diff_debt_snapshot(
    existing: Iterable[DebtLedgerRow],
    incoming: Iterable[IncomingDebtRow],
    *,
    new_id: Callable[[], str] = _new_id,
) -> DebtSnapshotDiff:
    stored = {row.key: row for row in existing}
    active = [row for row in stored.values() if not row.deleted]
    frontier = max((row.occurred_at.date() for row in active), default=None)
    baseline = frontier is None

    balance_before: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in active:
        balance_before[row.customer_id] += _money(row.amount)
    balance_after: dict[str, Decimal] = defaultdict(lambda: ZERO)

    inserts: list[DebtLedgerRow] = []
    updates: list[DebtLedgerRow] = []
    restores: list[DebtLedgerRow] = []
    changes: list[DebtTransactionChange] = []
    unchanged = 0
    seen: set[tuple[str, str]] = set()

    for row in incoming:
        if row.key in seen:
            raise DuplicateDebtTransactionsError()
        seen.add(row.key)
        balance_after[row.customer_id] += _money(row.amount)
        old = stored.get(row.key)
        if old is None:
            new = _written(row, new_id())
            inserts.append(new)
            if frontier is not None and row.occurred_at.date() < frontier:
                changes.append(_change(DebtChangeType.BACKDATED_INSERT, old=None, new=new))
            continue
        new = _written(row, old.debt_transaction_id)
        if old.deleted:
            restores.append(new)
            changes.append(_change(DebtChangeType.RESTORED, old=old, new=new))
        elif _same_values(old, row):
            unchanged += 1
        else:
            updates.append(new)
            changes.append(_change(DebtChangeType.UPDATED, old=old, new=new))

    missing = sorted(
        (row for row in active if row.key not in seen),
        key=lambda row: (row.occurred_at, row.source_type, row.source_id),
    )
    for row in missing:
        changes.append(_change(DebtChangeType.DELETED, old=row, new=None))

    if baseline:
        changes = []
    return DebtSnapshotDiff(
        inserts=tuple(inserts),
        updates=tuple(updates),
        restores=tuple(restores),
        deletes=tuple(row.debt_transaction_id for row in missing),
        unchanged=unchanged,
        changes=tuple(changes),
        revisions=_revisions(changes, balance_before, balance_after),
        frontier_date=frontier,
        is_baseline=baseline,
    )
