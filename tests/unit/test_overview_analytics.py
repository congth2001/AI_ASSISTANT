from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from config.container import container
from main import create_app
from src.modules.analytics.application.use_cases.dashboard_analytics_use_case import DashboardAnalyticsUseCase
from src.modules.analytics.domain.models.dashboard import DashboardFilters, TimeGrain, TimeSeriesPoint
from src.modules.analytics.domain.models.overview import DataFreshness, OverviewInsightSnapshot
from src.modules.auth.presentation.router import get_current_user


@pytest.mark.asyncio
async def test_comparison_aligns_sparse_days_across_months_and_keeps_negative_returns():
    class Repository:
        calls = []

        async def get_time_series(self, filters, grain):
            self.calls.append((filters, grain))
            if len(self.calls) == 1:
                return [TimeSeriesPoint(date(2025, 3, 31), Decimal('100.10'), 1),
                        TimeSeriesPoint(date(2025, 4, 2), Decimal('-20.25'), 0)]
            return [TimeSeriesPoint(date(2025, 3, 27), Decimal('50.05'), 1),
                    TimeSeriesPoint(date(2025, 3, 30), Decimal('30.30'), 2)]

    repo = Repository()
    filters = DashboardFilters(date(2025, 3, 31), date(2025, 4, 4), ward_names=('Xã A',))
    result = await DashboardAnalyticsUseCase(repo).get_time_series_comparison(filters, TimeGrain.MONTH)

    assert [p.period_start for p in result] == [date(2025, 3, 31), date(2025, 4, 1)]
    assert result[0].period_end == date(2025, 4, 1)
    assert result[0].previous_period_start == date(2025, 3, 27)
    assert result[0].previous_period_end == date(2025, 3, 28)
    assert result[1].previous_period_start == date(2025, 3, 28)
    assert result[1].previous_period_end == date(2025, 3, 31)
    assert [p.revenue for p in result] == [Decimal('100.10'), Decimal('-20.25')]
    assert [p.previous_revenue for p in result] == [Decimal('50.05'), Decimal('30.30')]
    assert [p.previous_invoice_count for p in result] == [1, 2]
    assert repo.calls == [(filters, TimeGrain.DAY), (filters.previous_period(), TimeGrain.DAY)]


@pytest.mark.asyncio
async def test_comparison_fills_empty_days_in_both_periods():
    class Repository:
        async def get_time_series(self, filters, grain):
            return []

    result = await DashboardAnalyticsUseCase(Repository()).get_time_series_comparison(
        DashboardFilters(date(2024, 2, 28), date(2024, 3, 2)), TimeGrain.DAY,
    )
    assert len(result) == 3
    assert result[1].period_start == date(2024, 2, 29)
    assert all(p.revenue == 0 and p.previous_revenue == 0 for p in result)


@pytest.mark.asyncio
async def test_overview_rejects_product_filters_instead_of_silently_ignoring_them():
    with pytest.raises(ValueError, match='customer and geography'):
        await DashboardAnalyticsUseCase(object()).get_overview_insights(
            DashboardFilters(date(2025, 3, 1), date(2025, 4, 1), product_names=('Gạch',)),
        )


@pytest.mark.parametrize('path', ['data-freshness', 'overview-insights', 'time-series-comparison'])
@pytest.mark.parametrize('role,expected', [(None, 401), ('guest', 403)])
def test_new_overview_routes_require_authenticated_business_roles(path, role, expected):
    app = create_app()
    if role:
        app.dependency_overrides[get_current_user] = lambda: {'id': 'guest-id', 'role': role}
    response = TestClient(app).get(f'/api/v1/analytics/{path}', params={
        'date_from': '2025-03-01', 'date_to': '2025-04-01',
    })
    assert response.status_code == expected


def test_overview_contract_preserves_period_geography_decimals_and_null_freshness():
    class UseCase:
        async def get_overview_insights(self, filters):
            assert filters.ward_names == ('Xã A',)
            assert filters.village_names == ('Thôn 1',)
            return OverviewInsightSnapshot((), 0, 0, Decimal('0.00'), (), Decimal('0.00'), 0,
                                           Decimal('0.00'), None, ())

        async def get_data_freshness(self):
            return DataFreshness(None, datetime(2025, 3, 20, 12, tzinfo=timezone.utc))

    container.dashboard_analytics_use_case.override(providers.Object(UseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {'id': 'staff', 'role': 'staff'}
        client = TestClient(app)
        result = client.get('/api/v1/analytics/overview-insights', params={
            'date_from': '2025-03-01', 'date_to': '2025-04-01', 'ward': 'Xã A', 'village': 'Thôn 1',
        })
        freshness = client.get('/api/v1/analytics/data-freshness')
    finally:
        container.dashboard_analytics_use_case.reset_override()
    assert result.status_code == 200
    assert result.json()['total_receivables'] == '0.00'
    assert result.json()['top_receivables_share_percent'] is None
    assert result.json()['previous_period']['date_from'] == '2025-01-29'
    assert result.json()['previous_period']['date_to'] == '2025-03-01'
    assert freshness.status_code == 200
    assert freshness.json() == {'latest_transaction_date': None, 'last_recorded_at': '2025-03-20T12:00:00Z'}


def test_comparison_api_contract():
    class Repository:
        async def get_time_series(self, filters, grain):
            return [TimeSeriesPoint(filters.date_from, Decimal('0.01'), 1)]

    container.dashboard_analytics_use_case.override(providers.Object(DashboardAnalyticsUseCase(Repository())))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {'id': 'admin', 'role': 'admin'}
        result = TestClient(app).get('/api/v1/analytics/time-series-comparison', params={
            'date_from': '2025-03-31', 'date_to': '2025-04-02', 'grain': 'month',
        })
    finally:
        container.dashboard_analytics_use_case.reset_override()
    assert result.status_code == 200
    assert result.json()['items'][0]['previous_revenue'] == '0.01'
    assert result.json()['items'][1]['revenue'] == '0'
