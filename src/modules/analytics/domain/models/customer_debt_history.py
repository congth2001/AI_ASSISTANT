"""Per-customer debt history and the audit trail of retroactive ledger changes.

Business rules: ``docs/customer-debt-history.md`` sections 3 and 5. All date ranges
here are inclusive on both ends (``date_to`` means "up to the end of that day").
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from src.modules.analytics.domain.errors import InvalidDebtHistoryDateRangeError

MAX_SERIES_POINTS = 400
MAX_LEDGER_ENTRIES = 50_000
MAX_CHANGES_PER_REVISION = 50
DEBT_SOURCE_TYPES = ("opening", "sale", "sales_return", "receipt")


class DebtHistoryGrain(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class DebtStatus(str, Enum):
    IN_DEBT = "in_debt"
    CREDIT = "credit"
    SETTLED = "settled"


class DebtAgingBucketKey(str, Enum):
    LE_3M = "le_3m"
    M3_TO_6M = "3m_6m"
    M6_TO_1Y = "6m_1y"
    Y1_TO_2Y = "1y_2y"
    Y2_TO_3Y = "2y_3y"
    OVER_3Y = "over_3y"


def _check_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise InvalidDebtHistoryDateRangeError()


@dataclass(frozen=True)
class DebtHistoryFilters:
    """``date_from=None`` means from the start of the ledger; ``date_to`` is the as-of day."""

    date_to: date
    date_from: date | None = None
    grain: DebtHistoryGrain = DebtHistoryGrain.MONTH

    def __post_init__(self) -> None:
        _check_range(self.date_from, self.date_to)


@dataclass(frozen=True)
class DebtHistoryEntryFilters:
    date_from: date | None = None
    date_to: date | None = None
    source_types: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _check_range(self.date_from, self.date_to)


@dataclass(frozen=True)
class DebtRevisionFilters:
    """Run dates (Vietnam local) of the system-wide revision list."""

    date_from: date | None = None
    date_to: date | None = None
    ward_names: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _check_range(self.date_from, self.date_to)


@dataclass(frozen=True)
class CustomerDebtProfile:
    customer_id: str
    customer_name: str
    address_detail: str | None
    village_name: str | None
    ward_name: str | None


@dataclass(frozen=True)
class DebtLedgerEntry:
    entry_id: str
    occurred_at: datetime
    source_type: str
    source_id: str
    amount: Decimal


@dataclass(frozen=True)
class DebtHistorySummary:
    """Period movements satisfy ``closing = opening + increase - receipt - return - other_decrease``.

    ``other_decrease_amount`` holds negative ``opening`` rows inside the period.
    """

    opening_balance: Decimal
    closing_balance: Decimal
    current_balance: Decimal
    increase_amount: Decimal
    receipt_amount: Decimal
    return_amount: Decimal
    other_decrease_amount: Decimal
    status: DebtStatus
    debt_since: date | None
    days_in_debt: int | None
    last_receipt_at: datetime | None
    last_receipt_amount: Decimal | None
    revision_count: int = 0
    last_revision_at: datetime | None = None
    last_revision_delta: Decimal | None = None


@dataclass(frozen=True)
class DebtBalancePoint:
    period_start: date
    closing_balance: Decimal
    increase: Decimal
    decrease: Decimal


@dataclass(frozen=True)
class DebtAgingBucket:
    bucket: DebtAgingBucketKey
    amount: Decimal


@dataclass(frozen=True)
class CustomerDebtHistory:
    customer: CustomerDebtProfile
    date_from: date | None
    date_to: date
    grain: DebtHistoryGrain
    summary: DebtHistorySummary
    aging: tuple[DebtAgingBucket, ...]
    series: tuple[DebtBalancePoint, ...]


@dataclass(frozen=True)
class DebtRevisionSummary:
    revision_count: int
    last_revision_at: datetime | None
    last_revision_delta: Decimal | None


@dataclass(frozen=True)
class DebtHistoryEntryCursor:
    occurred_at: datetime
    type_order: int
    source_id: str


@dataclass(frozen=True)
class DebtHistoryEntry:
    entry_id: str
    occurred_at: datetime
    source_type: str
    source_id: str
    voucher_number: str
    invoice_id: str | None
    return_id: str | None
    amount: Decimal
    balance_after: Decimal
    revised: bool
    last_revised_at: datetime | None


@dataclass(frozen=True)
class DebtHistoryEntryPage:
    items: tuple[DebtHistoryEntry, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class DebtRevisionChangeItem:
    change_type: str
    source_type: str
    source_id: str
    voucher_number: str
    customer_id: str
    previous_customer_id: str | None
    old_occurred_at: datetime | None
    new_occurred_at: datetime | None
    old_amount: Decimal | None
    new_amount: Decimal | None
    balance_delta: Decimal


@dataclass(frozen=True)
class RunCursor:
    """Keyset position in a newest-first list of runs (optionally per customer)."""

    started_at: datetime
    run_id: str
    customer_id: str | None = None


@dataclass(frozen=True)
class CustomerDebtRevisionItem:
    run_id: str
    run_at: datetime
    entrypoint: str
    balance_before: Decimal
    balance_after: Decimal
    balance_delta: Decimal
    earliest_affected_at: datetime
    change_count: int
    changes: tuple[DebtRevisionChangeItem, ...]
    has_more_changes: bool


@dataclass(frozen=True)
class CustomerDebtRevisionPage:
    items: tuple[CustomerDebtRevisionItem, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class DebtRevisionListItem:
    run_id: str
    run_at: datetime
    customer_id: str
    customer_name: str
    ward_name: str | None
    village_name: str | None
    balance_before: Decimal
    balance_after: Decimal
    balance_delta: Decimal
    earliest_affected_at: datetime
    change_count: int


@dataclass(frozen=True)
class LatestSyncRun:
    run_id: str
    run_at: datetime
    entrypoint: str
    is_baseline: bool
    revised_customers: int
    retroactive_delta: Decimal


@dataclass(frozen=True)
class DebtRevisionListPage:
    latest_run: LatestSyncRun | None
    items: tuple[DebtRevisionListItem, ...]
    next_cursor: str | None
    has_more: bool
