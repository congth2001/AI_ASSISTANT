"""Stable API contracts shared by dashboard endpoints."""

from datetime import date
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

