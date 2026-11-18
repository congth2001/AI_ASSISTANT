"""Domain filters and query results for customer debt."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from src.modules.analytics.domain.errors import (
    InvalidExportDateRangeError,
    VillageWardRequiredError,
)


class CustomerDebtSheetMode(str, Enum):
    SINGLE = "single"
    VILLAGE = "village"
    WARD = "ward"


@dataclass(frozen=True)
class CustomerDebtWardSummary:
    ward_name: str
    debtor_customers: int
    receivables: Decimal


@dataclass(frozen=True)
class CustomerOverviewMetrics:
    total_customers: int
    purchasing_customers: int
    debtor_customers: int
    non_debtor_customers: int
    total_revenue: Decimal
    invoice_count: int
    receivables: Decimal
    advances: Decimal
    net_balance: Decimal
    debt_by_ward: tuple[CustomerDebtWardSummary, ...]


@dataclass(frozen=True)
class CustomerOverviewItem:
    key: str
    label: str
    ward_name: str | None
    village_name: str | None
    revenue: Decimal
    invoice_count: int
    last_purchase_at: datetime | None
    current_debt: Decimal


@dataclass(frozen=True)
class CustomerOverviewCursor:
    current_debt: Decimal
    revenue: Decimal
    label: str
    key: str


@dataclass(frozen=True)
class CustomerOverviewPage:
    metrics: CustomerOverviewMetrics
    items: tuple[CustomerOverviewItem, ...]
    total: int
    limit: int
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class CustomerDebtExportFilters:
    """Optional inclusive date range and multi-value customer filters."""

    date_from: date | None = None
    date_to: date | None = None
    customer_ids: tuple[str, ...] = field(default_factory=tuple)
    ward_names: tuple[str, ...] = field(default_factory=tuple)
    positive_debt_only: bool = False
    sheet_mode: CustomerDebtSheetMode = CustomerDebtSheetMode.SINGLE

    def __post_init__(self) -> None:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise InvalidExportDateRangeError()
        if self.sheet_mode == CustomerDebtSheetMode.VILLAGE and not self.ward_names:
            raise VillageWardRequiredError()


@dataclass(frozen=True)
class CustomerDebtExportItem:
    key: str
    label: str
    ward_name: str | None
    village_name: str | None
    address_detail: str | None
    current_debt: Decimal
