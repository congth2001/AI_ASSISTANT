"""Domain value objects and results for deterministic dashboard analytics."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum


class TimeGrain(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class RankingDimension(str, Enum):
    CUSTOMER = "customer"
    PRODUCT = "product"
    CATEGORY = "category"


class CustomerDebtSheetMode(str, Enum):
    SINGLE = "single"
    VILLAGE = "village"
    WARD = "ward"


@dataclass(frozen=True)
class DashboardFilters:
    """Reusable analytics filters using a closed-open date interval."""

    date_from: date
    date_to: date
    customer_id: str | None = None
    ward_names: tuple[str, ...] = field(default_factory=tuple)
    village_names: tuple[str, ...] = field(default_factory=tuple)
    category_names: tuple[str, ...] = field(default_factory=tuple)
    product_names: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.date_from >= self.date_to:
            raise ValueError("date_from must be before date_to")

    @property
    def day_count(self) -> int:
        return (self.date_to - self.date_from).days

    def previous_period(self) -> "DashboardFilters":
        duration = timedelta(days=self.day_count)
        return DashboardFilters(
            date_from=self.date_from - duration,
            date_to=self.date_from,
            customer_id=self.customer_id,
            ward_names=self.ward_names,
            village_names=self.village_names,
            category_names=self.category_names,
            product_names=self.product_names,
        )


@dataclass(frozen=True)
class DashboardMetricSnapshot:
    total_revenue: Decimal
    invoice_count: int
    customer_count: int
    average_invoice_value: Decimal
    net_debt_delta: Decimal


@dataclass(frozen=True)
class DashboardSummary:
    current: DashboardMetricSnapshot
    previous_revenue: Decimal
    revenue_change: Decimal
    revenue_growth_percent: Decimal | None


@dataclass(frozen=True)
class TimeSeriesPoint:
    period_start: date
    revenue: Decimal
    invoice_count: int


@dataclass(frozen=True)
class RankingItem:
    key: str
    label: str
    revenue: Decimal
    invoice_count: int
    quantity: Decimal | None = None
    unit_name: str | None = None


@dataclass(frozen=True)
class RankingPage:
    dimension: RankingDimension
    items: tuple[RankingItem, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class FilterOption:
    value: str
    label: str


@dataclass(frozen=True)
class DashboardFilterOptions:
    customers: tuple[FilterOption, ...]
    wards: tuple[str, ...]
    villages: tuple[str, ...]
    categories: tuple[str, ...]
    products: tuple[str, ...]


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
            raise ValueError("date_from must be before or equal to date_to")
        if self.sheet_mode == CustomerDebtSheetMode.VILLAGE and not self.ward_names:
            raise ValueError("Village sheets require at least one ward filter")


@dataclass(frozen=True)
class CustomerDebtExportItem:
    key: str
    label: str
    ward_name: str | None
    village_name: str | None
    address_detail: str | None
    current_debt: Decimal


@dataclass(frozen=True)
class OrderFilters:
    date_from: date | None = None
    date_to: date | None = None
    invoice_number: str | None = None
    customer_id: str | None = None
    ward_names: tuple[str, ...] = field(default_factory=tuple)
    village_names: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.date_from and self.date_to and self.date_from >= self.date_to:
            raise ValueError("date_from must be before date_to")


@dataclass(frozen=True)
class OrderSummary:
    invoice_id: str
    invoice_number: str
    issued_at: datetime
    customer_name: str
    customer_ward_name: str | None
    customer_village_name: str | None
    invoice_total_amount: Decimal
    line_count: int


@dataclass(frozen=True)
class OrderLine:
    line_number: int
    product_name: str
    product_category_name: str | None
    unit_name: str
    unit_price: Decimal
    quantity: Decimal
    line_amount: Decimal


@dataclass(frozen=True)
class OrderDetail:
    invoice_id: str
    invoice_number: str
    issued_at: datetime
    customer_name: str
    customer_address_detail: str | None
    customer_ward_name: str | None
    customer_village_name: str | None
    invoice_total_amount: Decimal
    lines: tuple[OrderLine, ...]


@dataclass(frozen=True)
class OrderPage:
    items: tuple[OrderSummary, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class OrderLedgerExportFilters:
    date_from: date | None = None
    date_to: date | None = None
    invoice_number: str | None = None
    customer_id: str | None = None
    ward_names: tuple[str, ...] = field(default_factory=tuple)
    village_names: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before or equal to date_to")


@dataclass(frozen=True)
class OrderLedgerExportItem:
    customer_id: str
    customer_name: str
    customer_address: str | None
    occurred_at: datetime
    voucher_number: str
    reason: str
    product_name: str | None
    unit_name: str | None
    unit_price: Decimal
    quantity: Decimal
    payment_amount: Decimal
    debt_amount: Decimal
    running_debt: Decimal


@dataclass(frozen=True)
class OrderLedgerExportData:
    customer_id: str
    customer_name: str
    customer_address: str | None
    items: tuple[OrderLedgerExportItem, ...] = field(default_factory=tuple)
