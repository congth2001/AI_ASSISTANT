"""Pure rules of the debt-ledger audit trail (docs/customer-debt-history.md, 3.3)."""
from datetime import date, datetime
from decimal import Decimal
from itertools import count

import pytest

from src.modules.sales.domain.errors import DuplicateDebtTransactionsError
from src.modules.sales.domain.models.debt_ledger import (
    DebtChangeType,
    DebtLedgerRow,
    IncomingDebtRow,
)
from src.modules.sales.domain.services.debt_snapshot_diff import diff_debt_snapshot

D = Decimal


def stored(source_id, customer="c1", when="2025-03-10 08:00", amount="100", *,
           source_type="sale", deleted=False):
    return DebtLedgerRow(
        debt_transaction_id=f"id-{source_type}-{source_id}",
        source_type=source_type, source_id=source_id, customer_id=customer,
        occurred_at=datetime.fromisoformat(when), amount=D(amount), deleted=deleted,
    )


def incoming(source_id, customer="c1", when="2025-03-10 08:00", amount="100", *,
             source_type="sale"):
    return IncomingDebtRow(
        source_type=source_type, source_id=source_id, customer_id=customer,
        occurred_at=datetime.fromisoformat(when), amount=D(amount),
    )


def ids():
    counter = count(1)
    return lambda: f"new-{next(counter)}"


def test_first_run_is_a_baseline_without_audit_rows():
    diff = diff_debt_snapshot([], [incoming("1"), incoming("2", when="2024-01-01")], new_id=ids())

    assert diff.is_baseline and diff.frontier_date is None
    assert [row.debt_transaction_id for row in diff.inserts] == ["new-1", "new-2"]
    assert diff.changes == () and diff.revisions == ()


def test_identical_snapshot_rewrites_nothing():
    rows = [stored("1"), stored("2", amount="-30.50", source_type="receipt")]
    diff = diff_debt_snapshot(
        rows,
        [incoming("1"), incoming("2", amount="-30.5", source_type="receipt")],
    )

    assert diff.unchanged == 2
    assert not (diff.inserts or diff.updates or diff.restores or diff.deletes or diff.changes)
    assert not diff.is_baseline and diff.frontier_date == date(2025, 3, 10)


def test_amount_change_is_recorded_with_its_balance_effect():
    diff = diff_debt_snapshot(
        [stored("1", amount="100"), stored("2", when="2025-03-12 09:00", amount="50")],
        [incoming("1", amount="160"), incoming("2", when="2025-03-12 09:00", amount="50")],
    )

    (change,) = diff.changes
    assert change.change_type is DebtChangeType.UPDATED
    assert (change.old_amount, change.new_amount, change.balance_delta) == (D("100.00"), D("160.00"), D("60.00"))
    assert change.debt_transaction_id == "id-sale-1"
    assert [row.debt_transaction_id for row in diff.updates] == ["id-sale-1"]
    (revision,) = diff.revisions
    assert revision.customer_id == "c1"
    assert (revision.balance_before, revision.balance_after, revision.balance_delta) == (D("150"), D("210"), D("60"))
    assert revision.earliest_affected_at == datetime(2025, 3, 10, 8)
    assert revision.change_count == 1


def test_date_only_change_is_recorded_with_zero_delta_and_earliest_date():
    diff = diff_debt_snapshot([stored("1")], [incoming("1", when="2025-02-01 08:00")])

    (change,) = diff.changes
    assert change.change_type is DebtChangeType.UPDATED and change.balance_delta == 0
    assert diff.revisions[0].earliest_affected_at == datetime(2025, 2, 1, 8)


def test_moving_a_row_to_another_customer_revises_both_customers():
    diff = diff_debt_snapshot(
        [stored("1", customer="c1", amount="100"), stored("2", customer="c2", amount="40")],
        [incoming("1", customer="c2", amount="100"), incoming("2", customer="c2", amount="40")],
    )

    (change,) = diff.changes
    assert change.customer_id == "c2" and change.previous_customer_id == "c1"
    assert change.balance_delta == 0
    by_customer = {r.customer_id: r for r in diff.revisions}
    assert by_customer["c1"].balance_delta == D("-100") and by_customer["c1"].balance_after == 0
    assert by_customer["c2"].balance_delta == D("100") and by_customer["c2"].balance_after == D("140")


def test_missing_row_is_deleted_and_lowers_the_balance():
    diff = diff_debt_snapshot(
        [stored("1"), stored("2", when="2025-03-01 07:00", amount="70")],
        [incoming("1")],
    )

    assert diff.deletes == ("id-sale-2",)
    (change,) = diff.changes
    assert change.change_type is DebtChangeType.DELETED
    assert change.new_amount is None and change.balance_delta == D("-70.00")
    assert diff.revisions[0].balance_after == D("100")


def test_reappearing_row_is_restored_with_its_full_amount():
    diff = diff_debt_snapshot(
        [stored("1"), stored("2", amount="70", deleted=True)],
        [incoming("1"), incoming("2", amount="80")],
    )

    assert [row.debt_transaction_id for row in diff.restores] == ["id-sale-2"]
    (change,) = diff.changes
    assert change.change_type is DebtChangeType.RESTORED
    assert (change.old_amount, change.new_amount, change.balance_delta) == (D("70.00"), D("80.00"), D("80.00"))


def test_new_rows_before_the_frontier_date_are_backdated_inserts():
    diff = diff_debt_snapshot(
        [stored("1", when="2025-03-10 08:00")],
        [
            incoming("1", when="2025-03-10 08:00"),
            incoming("old", when="2025-03-09 23:59", amount="25"),
            incoming("same-day", when="2025-03-10 06:00"),  # on the frontier date: ordinary
            incoming("later", when="2025-03-11 08:00"),
        ],
        new_id=ids(),
    )

    assert len(diff.inserts) == 3
    (change,) = diff.changes
    assert change.change_type is DebtChangeType.BACKDATED_INSERT
    assert change.source_id == "old" and change.debt_transaction_id == "new-1"
    assert change.old_amount is None and change.balance_delta == D("25.00")
    assert diff.backdated_count == 1
    revision = diff.revisions[0]
    assert revision.balance_delta == D("25") and revision.balance_after == D("325")


def test_frontier_ignores_soft_deleted_rows():
    diff = diff_debt_snapshot(
        [stored("1", when="2025-03-01 08:00"), stored("x", when="2026-01-01 08:00", deleted=True)],
        [incoming("1", when="2025-03-01 08:00")],
    )

    assert diff.frontier_date == date(2025, 3, 1)


def test_customers_without_changes_get_no_revision():
    diff = diff_debt_snapshot(
        [stored("1", customer="c1"), stored("2", customer="c2")],
        [incoming("1", customer="c1", amount="90"), incoming("2", customer="c2"),
         incoming("3", customer="c3", when="2025-03-11 08:00")],
    )

    assert [r.customer_id for r in diff.revisions] == ["c1"]
    assert diff.retroactive_delta == D("-10")


def test_several_changes_for_one_customer_are_summed():
    diff = diff_debt_snapshot(
        [stored("1", amount="100"), stored("2", when="2025-01-05 08:00", amount="50"),
         stored("3", when="2025-03-15 08:00", amount="10")],
        [incoming("1", amount="120"), incoming("3", when="2025-03-15 08:00", amount="10")],
    )

    (revision,) = diff.revisions
    assert revision.change_count == 2
    assert revision.balance_delta == D("-30")
    assert revision.earliest_affected_at == datetime(2025, 1, 5, 8)
    assert revision.balance_before == D("160") and revision.balance_after == D("130")


def test_duplicate_snapshot_keys_are_rejected():
    with pytest.raises(DuplicateDebtTransactionsError):
        diff_debt_snapshot([], [incoming("1"), incoming("1")])
