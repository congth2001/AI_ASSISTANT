from decimal import Decimal

from dependency_injector import providers
from main import create_app
from fastapi.testclient import TestClient

from config.container import container
from src.application.use_cases.dashboard_analytics_use_case import (
    DashboardAnalyticsUseCase,
)
from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardMetricSnapshot,
    DashboardSummary,
    CustomerOverviewItem,
    CustomerOverviewMetrics,
    CustomerOverviewPage,
)
from src.presentation.api.v1.auth import get_current_user


def test_dashboard_analytics_routes_are_exposed_in_openapi():
    paths = create_app().openapi()["paths"]

    assert "/api/v1/analytics/summary" in paths
    assert "/api/v1/analytics/time-series" in paths
    assert "/api/v1/analytics/rankings/{dimension}" in paths
    assert "/api/v1/analytics/filter-options" in paths
    assert "/api/v1/analytics/customer-overview" in paths

    assert "security" in paths["/api/v1/analytics/summary"]["get"]


def test_dashboard_analytics_rejects_unauthenticated_requests():
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/analytics/summary",
        params={"date_from": "2025-03-01", "date_to": "2025-04-01"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_dashboard_analytics_rejects_guest_role():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "guest-id",
        "role": "guest",
    }
    client = TestClient(app)

    response = client.get(
        "/api/v1/analytics/summary",
        params={"date_from": "2025-03-01", "date_to": "2025-04-01"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"


def test_dashboard_summary_contract_for_staff():
    class FakeUseCase:
        async def get_summary(self, filters):
            metrics = DashboardMetricSnapshot(
                total_revenue=Decimal("7000.00"),
                invoice_count=3,
                customer_count=2,
                average_invoice_value=Decimal("2333.33"),
                net_debt_delta=Decimal("500.00"),
            )
            return DashboardSummary(
                current=metrics,
                previous_revenue=Decimal("5200.00"),
                revenue_change=Decimal("1800.00"),
                revenue_growth_percent=Decimal("34.62"),
            )

    container.dashboard_analytics_use_case.override(providers.Object(FakeUseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/summary",
            params={"date_from": "2025-03-01", "date_to": "2025-04-01"},
        )
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == {
        "date_from": "2025-03-01",
        "date_to": "2025-04-01",
        "end_exclusive": True,
        "timezone": "Asia/Ho_Chi_Minh",
    }
    assert body["metrics"]["total_revenue"] == "7000.00"
    assert body["comparison"]["revenue_growth_percent"] == "34.62"


def test_filter_options_api_forwards_geography_context():
    class FakeUseCase:
        received = None

        async def get_filter_options(
            self, search, limit, ward_names=(), village_names=()
        ):
            self.received = (search, limit, ward_names, village_names)
            return DashboardFilterOptions((), (), (), (), ())

    fake = FakeUseCase()
    container.dashboard_analytics_use_case.override(providers.Object(fake))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/filter-options",
            params=[
                ("search", "An"),
                ("limit", "20"),
                ("ward", "Minh Khai"),
                ("village", "Thôn 1"),
            ],
        )
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 200
    assert fake.received == (
        "An",
        20,
        ("Minh Khai",),
        ("Thôn 1",),
    )


def test_customer_overview_contract_for_staff():
    class FakeUseCase:
        async def get_customer_overview(self, filters, limit, cursor):
            assert cursor is None
            return CustomerOverviewPage(
                metrics=CustomerOverviewMetrics(
                    total_customers=2,
                    purchasing_customers=1,
                    total_revenue=Decimal("7000.00"),
                    invoice_count=3,
                    receivables=Decimal("1200.00"),
                    advances=Decimal("200.00"),
                    net_balance=Decimal("1000.00"),
                ),
                items=(
                    CustomerOverviewItem(
                        key="customer-id",
                        label="Khách hàng A",
                        ward_name="Minh Khai",
                        village_name=None,
                        revenue=Decimal("7000.00"),
                        invoice_count=3,
                        last_purchase_at=None,
                        current_debt=Decimal("1200.00"),
                    ),
                ),
                total=2,
                limit=limit,
                next_cursor="next-page-token",
                has_more=True,
            )

    container.dashboard_analytics_use_case.override(providers.Object(FakeUseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/customer-overview",
            params={"date_from": "2025-03-01", "date_to": "2025-04-01"},
        )
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["receivables"] == "1200.00"
    assert body["metrics"]["advances"] == "200.00"
    assert body["items"][0]["current_debt"] == "1200.00"
    assert body["next_cursor"] == "next-page-token"
    assert body["has_more"] is True
    assert "offset" not in body


def test_customer_overview_rejects_invalid_cursor():
    container.dashboard_analytics_use_case.override(
        providers.Object(DashboardAnalyticsUseCase(repository=object()))
    )
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/customer-overview",
            params={
                "date_from": "2025-03-01",
                "date_to": "2025-04-01",
                "cursor": "invalid-cursor",
            },
        )
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid customer overview cursor"
