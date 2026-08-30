"""Stable API contracts shared by dashboard endpoints."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsPeriodResponse(BaseModel):
    date_from: date
    date_to: date
    end_exclusive: bool = True
    timezone: str = "Asia/Ho_Chi_Minh"


class MetricSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_revenue: Decimal
    invoice_count: int
    customer_count: int
    average_invoice_value: Decimal
    net_debt_delta: Decimal


class RevenueComparisonResponse(BaseModel):
    previous_revenue: Decimal
    revenue_change: Decimal
    revenue_growth_percent: Decimal | None


class AnalyticsSummaryResponse(BaseModel):
    period: AnalyticsPeriodResponse
    metrics: MetricSnapshotResponse
    comparison: RevenueComparisonResponse


class TimeSeriesPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_start: date
    revenue: Decimal
    invoice_count: int


class TimeSeriesResponse(BaseModel):
    period: AnalyticsPeriodResponse
    grain: str
    items: list[TimeSeriesPointResponse]


class RankingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    revenue: Decimal
    invoice_count: int
    quantity: Decimal | None = None
    unit_name: str | None = None


class RankingResponse(BaseModel):
    period: AnalyticsPeriodResponse
    dimension: str
    items: list[RankingItemResponse]
    total: int
    limit: int
    offset: int


class FilterOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: str
    label: str


class AnalyticsFilterOptionsResponse(BaseModel):
    customers: list[FilterOptionResponse]
    wards: list[str]
    villages: list[str]
    categories: list[str]
    products: list[str]


class CustomerDebtWardSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ward_name: str
    debtor_customers: int
    receivables: Decimal


class CustomerOverviewMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_customers: int
    purchasing_customers: int
    debtor_customers: int
    non_debtor_customers: int
    total_revenue: Decimal
    invoice_count: int
    receivables: Decimal
    advances: Decimal
    net_balance: Decimal
    debt_by_ward: list[CustomerDebtWardSummaryResponse]


class CustomerOverviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    ward_name: str | None
    village_name: str | None
    revenue: Decimal
    invoice_count: int
    last_purchase_at: datetime | None
    current_debt: Decimal


class CustomerOverviewResponse(BaseModel):
    period: AnalyticsPeriodResponse
    metrics: CustomerOverviewMetricsResponse
    items: list[CustomerOverviewItemResponse]
    total: int
    limit: int
    next_cursor: str | None
    has_more: bool


class OrderSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: str
    invoice_number: str
    issued_at: datetime
    customer_name: str
    customer_ward_name: str | None
    customer_village_name: str | None
    invoice_total_amount: Decimal
    line_count: int


class OrderPageResponse(BaseModel):
    items: list[OrderSummaryResponse]
    total: int
    limit: int
    offset: int


class OrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_number: int
    product_name: str
    product_category_name: str | None
    unit_name: str
    unit_price: Decimal
    quantity: Decimal
    line_amount: Decimal


class OrderDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: str
    invoice_number: str
    issued_at: datetime
    customer_name: str
    customer_address_detail: str | None
    customer_ward_name: str | None
    customer_village_name: str | None
    invoice_total_amount: Decimal
    lines: list[OrderLineResponse]
