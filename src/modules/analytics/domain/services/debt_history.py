"""Pure computations behind the customer debt-history page (no I/O).

Ordering matches the order-ledger export: by ``occurred_at``, then ``opening`` ->
``sale`` -> ``sales_return`` -> ``receipt``, then ``source_id``. Aging is FIFO over the
whole ledger up to the as-of day; see ``docs/customer-debt-history.md`` section 3.
"""
from calendar import monthrange
from collections import deque
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from src.modules.analytics.domain.errors import DebtHistoryTooManyPointsError
from src.modules.analytics.domain.models.customer_debt_history import (
    MAX_SERIES_POINTS,
    DebtAgingBucket,
    DebtAgingBucketKey,
    DebtBalancePoint,
    DebtHistoryGrain,
    DebtHistorySummary,
    DebtLedgerEntry,
    DebtStatus,
)

ZERO = Decimal("0")
TYPE_ORDER = {"opening": 0, "sale": 1, "sales_return": 2, "receipt": 3}
UNKNOWN_TYPE_ORDER = 9

# Upper month bound of each bucket, oldest bucket last (no bound).
AGING_BOUNDS: tuple[tuple[DebtAgingBucketKey, int | None], ...] = (
    (DebtAgingBucketKey.LE_3M, 3),
    (DebtAgingBucketKey.M3_TO_6M, 6),
    (DebtAgingBucketKey.M6_TO_1Y, 12),
    (DebtAgingBucketKey.Y1_TO_2Y, 24),
    (DebtAgingBucketKey.Y2_TO_3Y, 36),
    (DebtAgingBucketKey.OVER_3Y, None),
)


def type_order(source_type: str) -> int:
    return TYPE_ORDER.get(source_type, UNKNOWN_TYPE_ORDER)


def entry_sort_key(entry: DebtLedgerEntry) -> tuple[datetime, int, str]:
    return (entry.occurred_at, type_order(entry.source_type), entry.source_id)


def order_entries(entries: Iterable[DebtLedgerEntry]) -> list[DebtLedgerEntry]:
    return sorted(entries, key=entry_sort_key)


def subtract_months(day: date, months: int) -> date:
    """Calendar month subtraction; the day is clamped to the end of the target month."""
    years, month_index = divmod(day.month - 1 - months, 12)
    year = day.year + years
    month = month_index + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def period_start(day: date, grain: DebtHistoryGrain) -> date:
    if grain is DebtHistoryGrain.DAY:
        return day
    if grain is DebtHistoryGrain.WEEK:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def next_period(start: date, grain: DebtHistoryGrain) -> date:
    if grain is DebtHistoryGrain.DAY:
        return start + timedelta(days=1)
    if grain is DebtHistoryGrain.WEEK:
        return start + timedelta(days=7)
    return date(start.year + start.month // 12, start.month % 12 + 1, 1)


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min)


def status_of(balance: Decimal) -> DebtStatus:
    if balance > 0:
        return DebtStatus.IN_DEBT
    if balance < 0:
        return DebtStatus.CREDIT
    return DebtStatus.SETTLED


def debt_since(ordered: list[DebtLedgerEntry]) -> date | None:
    """Day the balance last turned positive and stayed positive to the end of ``ordered``."""
    running = ZERO
    since: date | None = None
    for entry in ordered:
        before = running
        running += entry.amount
        if before <= 0 < running:
            since = entry.occurred_at.date()
        elif running <= 0:
            since = None
    return since


def fifo_aging(ordered: list[DebtLedgerEntry], as_of: date) -> tuple[DebtAgingBucket, ...]:
    """Age the open balance: every decrease pays the oldest open increase first.

    A decrease larger than everything open becomes a credit that absorbs later
    increases. With a non-positive balance all buckets are zero.
    """
    open_items: deque[list] = deque()  # [day, remaining]
    credit = ZERO
    for entry in ordered:
        amount = entry.amount
        if amount > 0:
            absorbed = min(credit, amount)
            credit -= absorbed
            amount -= absorbed
            if amount > 0:
                open_items.append([entry.occurred_at.date(), amount])
        elif amount < 0:
            payment = -amount
            while payment > 0 and open_items:
                head = open_items[0]
                used = min(head[1], payment)
                head[1] -= used
                payment -= used
                if head[1] == 0:
                    open_items.popleft()
            credit += payment

    totals = {key: ZERO for key, _ in AGING_BOUNDS}
    cutoffs = [
        (key, subtract_months(as_of, months) if months is not None else None)
        for key, months in AGING_BOUNDS
    ]
    for day, remaining in open_items:
        for key, cutoff in cutoffs:
            if cutoff is None or day > cutoff:
                totals[key] += remaining
                break
    return tuple(DebtAgingBucket(bucket=key, amount=totals[key]) for key, _ in AGING_BOUNDS)


def balance_series(
    ordered: list[DebtLedgerEntry],
    date_from: date | None,
    date_to: date,
    grain: DebtHistoryGrain,
) -> tuple[DebtBalancePoint, ...]:
    """Closing balance and movements of every period from ``date_from`` to ``date_to``.

    Without ``date_from`` the series starts at the first entry (or ``date_to`` for an
    empty ledger). Periods without movements carry the previous balance.
    """
    first_day = date_from or (ordered[0].occurred_at.date() if ordered else date_to)
    first_day = min(first_day, date_to)
    starts: list[date] = []
    cursor = period_start(first_day, grain)
    while cursor <= date_to:
        starts.append(cursor)
        if len(starts) > MAX_SERIES_POINTS:
            raise DebtHistoryTooManyPointsError(max_points=MAX_SERIES_POINTS)
        cursor = next_period(cursor, grain)

    range_start = _start_of(first_day)
    range_end = _start_of(date_to + timedelta(days=1))
    running = ZERO
    index = 0
    while index < len(ordered) and ordered[index].occurred_at < range_start:
        running += ordered[index].amount
        index += 1

    points: list[DebtBalancePoint] = []
    for start in starts:
        period_end = min(_start_of(next_period(start, grain)), range_end)
        increase = decrease = ZERO
        while index < len(ordered) and ordered[index].occurred_at < period_end:
            amount = ordered[index].amount
            running += amount
            if amount > 0:
                increase += amount
            else:
                decrease -= amount
            index += 1
        points.append(DebtBalancePoint(
            period_start=start, closing_balance=running, increase=increase, decrease=decrease,
        ))
    return tuple(points)


def summarize(
    ordered: list[DebtLedgerEntry],
    date_from: date | None,
    date_to: date,
    *,
    current_balance: Decimal,
) -> DebtHistorySummary:
    """Period summary of ``ordered``, which must hold every entry before the end of ``date_to``."""
    range_start = _start_of(date_from) if date_from else None
    range_end = _start_of(date_to + timedelta(days=1))
    opening = closing = increase = receipts = returns = other = ZERO
    last_receipt: DebtLedgerEntry | None = None
    in_range: list[DebtLedgerEntry] = []
    for entry in ordered:
        if entry.occurred_at >= range_end:
            continue
        in_range.append(entry)
        closing += entry.amount
        if entry.source_type == "receipt":
            last_receipt = entry
        if range_start is not None and entry.occurred_at < range_start:
            opening += entry.amount
            continue
        if entry.amount > 0:
            increase += entry.amount
        elif entry.source_type == "receipt":
            receipts -= entry.amount
        elif entry.source_type == "sales_return":
            returns -= entry.amount
        else:
            other -= entry.amount

    since = debt_since(in_range) if closing > 0 else None
    return DebtHistorySummary(
        opening_balance=opening,
        closing_balance=closing,
        current_balance=current_balance,
        increase_amount=increase,
        receipt_amount=receipts,
        return_amount=returns,
        other_decrease_amount=other,
        status=status_of(closing),
        debt_since=since,
        days_in_debt=(date_to - since).days if since else None,
        last_receipt_at=last_receipt.occurred_at if last_receipt else None,
        last_receipt_amount=-last_receipt.amount if last_receipt else None,
    )
