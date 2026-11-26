"""HTTP contracts of the customer debt-history page (money as exact decimals)."""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.modules.analytics.domain.models.customer_debt_history import (
    DebtAgingBucketKey,
    DebtHistoryGrain,
    DebtStatus,
)


class _FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerDebtProfileResponse(_FromAttributes):
    customer_id: str
    customer_name: str
    address_detail: str | None
    village_name: str | None
    ward_name: str | None


class DebtHistorySummaryResponse(_FromAttributes):
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
    revision_count: int
    last_revision_at: datetime | None
    last_revision_delta: Decimal | None


class DebtAgingBucketResponse(_FromAttributes):
    bucket: DebtAgingBucketKey
    amount: Decimal


class DebtBalancePointResponse(_FromAttributes):
    period_start: date
    closing_balance: Decimal
    increase: Decimal
    decrease: Decimal


class CustomerDebtHistoryResponse(_FromAttributes):
    customer: CustomerDebtProfileResponse
    date_from: date | None
    date_to: date
    grain: DebtHistoryGrain
    timezone: str = "Asia/Ho_Chi_Minh"
    summary: DebtHistorySummaryResponse
    aging: list[DebtAgingBucketResponse]
    series: list[DebtBalancePointResponse]


class DebtHistoryEntryResponse(_FromAttributes):
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


class DebtHistoryEntryPageResponse(_FromAttributes):
    items: list[DebtHistoryEntryResponse]
    next_cursor: str | None
    has_more: bool


class DebtRevisionChangeResponse(_FromAttributes):
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


class CustomerDebtRevisionResponse(_FromAttributes):
    run_id: str
    run_at: datetime
    entrypoint: str
    balance_before: Decimal
    balance_after: Decimal
    balance_delta: Decimal
    earliest_affected_at: datetime
    change_count: int
    changes: list[DebtRevisionChangeResponse]
    has_more_changes: bool


class CustomerDebtRevisionPageResponse(_FromAttributes):
    items: list[CustomerDebtRevisionResponse]
    next_cursor: str | None
    has_more: bool


class DebtRevisionListItemResponse(_FromAttributes):
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


class LatestSyncRunResponse(_FromAttributes):
    run_id: str
    run_at: datetime
    entrypoint: str
    is_baseline: bool
    revised_customers: int
    retroactive_delta: Decimal


class DebtRevisionListPageResponse(_FromAttributes):
    latest_run: LatestSyncRunResponse | None
    items: list[DebtRevisionListItemResponse]
    next_cursor: str | None
    has_more: bool
