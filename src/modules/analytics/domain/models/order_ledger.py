"""Domain filters and query results for order ledger."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from src.modules.analytics.domain.errors import (
    InvalidExportDateRangeError,
)


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
            raise InvalidExportDateRangeError()


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
