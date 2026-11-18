"""Read models for overview comparisons, freshness and actionable insights."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class DataFreshness:
    latest_transaction_date: date | None
    last_recorded_at: datetime | None


@dataclass(frozen=True)
class CustomerRevenueMovement:
    customer_id: str
    customer_name: str
    ward_name: str | None
    village_name: str | None
    current_revenue: Decimal
    previous_revenue: Decimal
    revenue_change: Decimal
    current_invoice_count: int
    previous_invoice_count: int


@dataclass(frozen=True)
class DebtConcentrationItem:
    customer_id: str
    customer_name: str
    ward_name: str | None
    village_name: str | None
    receivables: Decimal


@dataclass(frozen=True)
class WardRevenueMovement:
    ward_name: str | None
    current_revenue: Decimal
    previous_revenue: Decimal
    revenue_change: Decimal


@dataclass(frozen=True)
class OverviewInsightSnapshot:
    declining_customers: tuple[CustomerRevenueMovement, ...]
    declining_customer_count: int
    inactive_customer_count: int
    declining_revenue_change: Decimal
    debt_customers: tuple[DebtConcentrationItem, ...]
    total_receivables: Decimal
    debtor_count: int
    top_receivables: Decimal
    top_receivables_share_percent: Decimal | None
    ward_movements: tuple[WardRevenueMovement, ...]


@dataclass(frozen=True)
class ComparedTimeSeriesPoint:
    period_start: date
    period_end: date
    previous_period_start: date
    previous_period_end: date
    revenue: Decimal
    previous_revenue: Decimal
    invoice_count: int
    previous_invoice_count: int
