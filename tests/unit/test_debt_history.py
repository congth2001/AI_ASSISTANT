"""Pure debt-history rules (docs/customer-debt-history.md, section 3)."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from src.modules.analytics.domain.errors import (
    DebtHistoryTooManyPointsError,
    InvalidDebtHistoryDateRangeError,
)
from src.modules.analytics.domain.models.customer_debt_history import (
    DebtAgingBucketKey as B,
    DebtHistoryFilters,
    DebtHistoryGrain as G,
    DebtLedgerEntry,
    DebtStatus,
)
from src.modules.analytics.domain.services.debt_history import (
    balance_series,
    debt_since,
    fifo_aging,
    order_entries,
    subtract_months,
    summarize,
)

D = Decimal


def e(when, amount, kind="sale", source_id=None):
    return DebtLedgerEntry(
        entry_id=f"id-{source_id or when}-{kind}", occurred_at=datetime.fromisoformat(when),
        source_type=kind, source_id=source_id or when, amount=D(str(amount)),
    )


def aging(entries, as_of):
    return {b.bucket: b.amount for b in fifo_aging(order_entries(entries), as_of)}


# --- ordering -------------------------------------------------------------------

def test_same_timestamp_orders_opening_sale_return_receipt_then_source_id():
    entries = [
        e("2025-03-01 08:00", -5, "receipt", "R1"),
        e("2025-03-01 08:00", -2, "sales_return", "T1"),
        e("2025-03-01 08:00", 10, "sale", "S2"),
        e("2025-03-01 08:00", 10, "sale", "S1"),
        e("2025-03-01 08:00", 1, "opening", "O1"),
    ]
    assert [x.source_id for x in order_entries(entries)] == ["O1", "S1", "S2", "T1", "R1"]


# --- months ---------------------------------------------------------------------

@pytest.mark.parametrize("day, months, expected", [
    (date(2026, 5, 31), 3, date(2026, 2, 28)),
    (date(2028, 5, 31), 3, date(2028, 2, 29)),   # leap year
    (date(2026, 1, 15), 1, date(2025, 12, 15)),
    (date(2026, 3, 31), 36, date(2023, 3, 31)),
    (date(2024, 2, 29), 12, date(2023, 2, 28)),
])
def test_subtract_months_clamps_to_month_end(day, months, expected):
    assert subtract_months(day, months) == expected


# --- aging ----------------------------------------------------------------------

def test_aging_buckets_use_calendar_month_boundaries():
    as_of = date(2026, 11, 19)
    entries = [
        e("2026-08-20 08:00", 1),   # > M(3)=2026-08-19 -> <=3m
        e("2026-08-19 08:00", 2),   # == M(3) -> 3-6m
        e("2026-05-19 08:00", 4),   # == M(6) -> 6m-1y
        e("2025-11-19 08:00", 8),   # == M(12) -> 1-2y
        e("2024-11-19 08:00", 16),  # == M(24) -> 2-3y
        e("2023-11-20 08:00", 32),  # > M(36) -> 2-3y
        e("2023-11-19 08:00", 64),  # == M(36) -> >3y
    ]
    assert aging(entries, as_of) == {
        B.LE_3M: D(1), B.M3_TO_6M: D(2), B.M6_TO_1Y: D(4), B.Y1_TO_2Y: D(8),
        B.Y2_TO_3Y: D(48), B.OVER_3Y: D(64),
    }


def test_payments_settle_the_oldest_debt_first():
    entries = [
        e("2024-01-10 08:00", 100),
        e("2026-10-01 08:00", 50),
        e("2026-11-01 08:00", -120, "receipt"),
    ]
    buckets = aging(entries, date(2026, 11, 19))
    assert buckets[B.LE_3M] == D(30) and sum(buckets.values()) == D(30)


def test_overpayment_becomes_credit_that_absorbs_later_debt():
    entries = [
        e("2025-01-01 08:00", 100),
        e("2025-02-01 08:00", -150, "receipt"),
        e("2026-10-01 08:00", 80),
    ]
    buckets = aging(entries, date(2026, 11, 19))
    assert buckets[B.LE_3M] == D(30) and sum(buckets.values()) == D(30)


def test_non_positive_balance_has_no_aging():
    entries = [e("2025-01-01 08:00", 100), e("2025-02-01 08:00", -100, "receipt")]
    assert set(aging(entries, date(2026, 11, 19)).values()) == {D(0)}
    credit = [e("2025-01-01 08:00", -10, "opening")]
    assert set(aging(credit, date(2026, 11, 19)).values()) == {D(0)}


def test_partial_return_reduces_the_oldest_open_item():
    entries = [
        e("2026-01-01 08:00", 100),
        e("2026-11-01 08:00", 40),
        e("2026-11-02 08:00", -30, "sales_return"),
    ]
    buckets = aging(entries, date(2026, 11, 19))
    assert buckets[B.M6_TO_1Y] == D(70) and buckets[B.LE_3M] == D(40)


# --- debt since -----------------------------------------------------------------

def test_debt_since_restarts_after_full_settlement():
    entries = order_entries([
        e("2025-01-05 08:00", 100),
        e("2025-02-01 08:00", -100, "receipt"),
        e("2025-03-10 08:00", 60),
        e("2025-04-01 08:00", -20, "receipt"),
    ])
    assert debt_since(entries) == date(2025, 3, 10)


def test_debt_since_counts_from_turning_positive_out_of_credit():
    entries = order_entries([
        e("2025-01-05 08:00", -50, "opening"),
        e("2025-02-01 08:00", 30),
        e("2025-03-01 08:00", 30),
    ])
    assert debt_since(entries) == date(2025, 3, 1)


# --- summary --------------------------------------------------------------------

def test_summary_splits_period_movements_and_keeps_the_invariant():
    entries = order_entries([
        e("2024-12-31 08:00", 500, "opening", "O"),
        e("2025-01-03 08:00", 200, "sale", "S1"),
        e("2025-01-04 08:00", -50, "sales_return", "T1"),
        e("2025-01-05 08:00", -300, "receipt", "R1"),
        e("2025-01-31 23:59", 10, "sale", "S2"),
        e("2025-02-01 00:00", 999, "sale", "S3"),   # after date_to: ignored
    ])
    s = summarize(entries, date(2025, 1, 1), date(2025, 1, 31), current_balance=D("1359"))

    assert s.opening_balance == D(500) and s.closing_balance == D(360)
    assert (s.increase_amount, s.receipt_amount, s.return_amount, s.other_decrease_amount) == (
        D(210), D(300), D(50), D(0))
    assert s.opening_balance + s.increase_amount - s.receipt_amount - s.return_amount == s.closing_balance
    assert s.status is DebtStatus.IN_DEBT and s.debt_since == date(2024, 12, 31)
    assert s.days_in_debt == 31
    assert s.last_receipt_at == datetime(2025, 1, 5, 8) and s.last_receipt_amount == D(300)
    assert s.current_balance == D("1359")


def test_summary_without_date_from_counts_everything_in_the_period():
    entries = order_entries([e("2020-01-01 08:00", 40, "opening"), e("2025-01-01 08:00", -60, "receipt")])
    s = summarize(entries, None, date(2025, 1, 31), current_balance=D(-20))

    assert s.opening_balance == 0 and s.closing_balance == D(-20)
    assert s.increase_amount == D(40) and s.receipt_amount == D(60)
    assert s.status is DebtStatus.CREDIT and s.debt_since is None and s.days_in_debt is None


def test_negative_opening_in_period_is_other_decrease():
    s = summarize([e("2025-01-02 08:00", -15, "opening")], date(2025, 1, 1), date(2025, 1, 31),
                  current_balance=D(-15))
    assert s.other_decrease_amount == D(15) and s.closing_balance == D(-15)


# --- series ---------------------------------------------------------------------

def test_monthly_series_carries_balance_through_empty_months():
    entries = order_entries([
        e("2024-12-15 08:00", 100),
        e("2025-01-10 08:00", 50),
        e("2025-01-20 08:00", -30, "receipt"),
        e("2025-03-05 08:00", 10),
    ])
    points = balance_series(entries, date(2025, 1, 1), date(2025, 3, 31), G.MONTH)

    assert [(p.period_start, p.closing_balance, p.increase, p.decrease) for p in points] == [
        (date(2025, 1, 1), D(120), D(50), D(30)),
        (date(2025, 2, 1), D(120), D(0), D(0)),
        (date(2025, 3, 1), D(130), D(10), D(0)),
    ]


def test_series_clips_partial_first_and_last_periods_to_the_range():
    entries = order_entries([
        e("2025-01-02 08:00", 5),     # before date_from, same month -> opening, not a movement
        e("2025-01-20 08:00", 7),
        e("2025-02-11 08:00", 100),   # after date_to, same month -> excluded
    ])
    points = balance_series(entries, date(2025, 1, 15), date(2025, 2, 10), G.MONTH)

    assert [(p.closing_balance, p.increase) for p in points] == [(D(12), D(7)), (D(12), D(0))]


def test_weekly_series_starts_on_monday_and_daily_series_has_one_point_per_day():
    weekly = balance_series([], date(2026, 11, 19), date(2026, 11, 30), G.WEEK)
    assert [p.period_start for p in weekly] == [date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30)]
    daily = balance_series([], date(2026, 11, 1), date(2026, 11, 30), G.DAY)
    assert len(daily) == 30


def test_series_without_date_from_starts_at_the_first_entry():
    entries = order_entries([e("2025-03-15 08:00", 10)])
    points = balance_series(entries, None, date(2025, 5, 31), G.MONTH)
    assert [p.period_start for p in points] == [date(2025, 3, 1), date(2025, 4, 1), date(2025, 5, 1)]
    assert balance_series([], None, date(2025, 5, 31), G.MONTH)[0].period_start == date(2025, 5, 1)


def test_series_rejects_more_than_400_points():
    with pytest.raises(DebtHistoryTooManyPointsError):
        balance_series([], date(2024, 1, 1), date(2025, 12, 31), G.DAY)


def test_filters_reject_reversed_range():
    with pytest.raises(InvalidDebtHistoryDateRangeError):
        DebtHistoryFilters(date_from=date(2025, 2, 1), date_to=date(2025, 1, 1))
