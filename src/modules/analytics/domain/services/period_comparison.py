"""Pure calculations that compare a report period with its previous period.

Shared by the dashboard use case and by the assistant's Overview reports so the
AI explains exactly the numbers the dashboard shows.
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from src.modules.analytics.domain.models.dashboard import (
    DashboardFilters,
    DashboardMetricSnapshot,
    DashboardSummary,
    TimeGrain,
    TimeSeriesPoint,
)
from src.modules.analytics.domain.models.overview import ComparedTimeSeriesPoint


def summarize_periods(
    current: DashboardMetricSnapshot, previous: DashboardMetricSnapshot
) -> DashboardSummary:
    """KPIs of the current period with revenue change/growth versus the previous one."""
    change = current.total_revenue - previous.total_revenue
    growth = None
    if previous.total_revenue != 0:
        growth = (change * Decimal("100") / previous.total_revenue).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return DashboardSummary(
        current=current,
        previous_revenue=previous.total_revenue,
        revenue_change=change,
        revenue_growth_percent=growth,
    )


def _bucket_key(day: date, grain: TimeGrain) -> date:
    if grain == TimeGrain.WEEK:
        return day - timedelta(days=day.weekday())
    if grain == TimeGrain.MONTH:
        return day.replace(day=1)
    if grain == TimeGrain.QUARTER:
        return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
    if grain == TimeGrain.YEAR:
        return day.replace(month=1, day=1)
    return day


def align_period_series(
    filters: DashboardFilters,
    grain: TimeGrain,
    current_days: Iterable[TimeSeriesPoint],
    previous_days: Iterable[TimeSeriesPoint],
) -> list[ComparedTimeSeriesPoint]:
    """Align equal-length periods by day offset, then bucket by current dates.

    ``current_days``/``previous_days`` are daily points. Calendar months/weeks may
    have different lengths and boundaries; bucketing both periods independently
    would compare different numbers of days.
    """
    current = {p.period_start: p for p in current_days}
    previous = {p.period_start: p for p in previous_days}
    previous_filters = filters.previous_period()
    buckets: dict[date, ComparedTimeSeriesPoint] = {}
    for offset in range(filters.day_count):
        day = filters.date_from + timedelta(days=offset)
        previous_day = previous_filters.date_from + timedelta(days=offset)
        key = _bucket_key(day, grain)
        if key not in buckets:
            buckets[key] = ComparedTimeSeriesPoint(
                day, day, previous_day, previous_day, Decimal(0), Decimal(0), 0, 0,
            )
        bucket = buckets[key]
        current_point, previous_point = current.get(day), previous.get(previous_day)
        buckets[key] = replace(
            bucket,
            period_end=day + timedelta(days=1),
            previous_period_end=previous_day + timedelta(days=1),
            revenue=bucket.revenue + (current_point.revenue if current_point else Decimal(0)),
            previous_revenue=bucket.previous_revenue + (previous_point.revenue if previous_point else Decimal(0)),
            invoice_count=bucket.invoice_count + (current_point.invoice_count if current_point else 0),
            previous_invoice_count=bucket.previous_invoice_count + (previous_point.invoice_count if previous_point else 0),
        )
    return list(buckets.values())
