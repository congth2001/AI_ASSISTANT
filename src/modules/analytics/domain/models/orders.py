"""Domain filters and query results for orders."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from src.modules.analytics.domain.errors import (
    InvalidReportDateRangeError,
)


@dataclass(frozen=True)
class OrderFilters:
    date_from: date | None = None
    date_to: date | None = None
    invoice_number: str | None = None
    customer_id: str | None = None
    ward_names: tuple[str, ...] = field(default_factory=tuple)
    village_names: tuple[str, ...] = field(default_factory=tuple)
    customer_geography: bool = False

    def __post_init__(self) -> None:
        if self.date_from and self.date_to and self.date_from >= self.date_to:
            raise InvalidReportDateRangeError()


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
    # Current customer of the invoice (links to the debt-history page).
    customer_id: str | None = None


@dataclass(frozen=True)
class OrderPage:
    items: tuple[OrderSummary, ...]
    total: int
    limit: int
    offset: int
