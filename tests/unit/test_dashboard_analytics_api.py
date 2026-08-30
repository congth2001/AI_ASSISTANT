from datetime import date, datetime
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
    CustomerDebtWardSummary,
    CustomerOverviewItem,
    CustomerOverviewMetrics,
    CustomerOverviewPage,
    OrderDetail,
    OrderLine,
    OrderPage,
    OrderSummary,
)
from src.presentation.api.v1.auth import get_current_user


def test_dashboard_analytics_routes_are_exposed_in_openapi():
    paths = create_app().openapi()["paths"]

    assert "/api/v1/analytics/summary" in paths
    assert "/api/v1/analytics/time-series" in paths
    assert "/api/v1/analytics/rankings/{dimension}" in paths
    assert "/api/v1/analytics/filter-options" in paths
    assert "/api/v1/analytics/customer-overview" in paths
    assert "/api/v1/analytics/customer-debt/export" in paths
    assert "/api/v1/analytics/orders" in paths
    assert "/api/v1/analytics/orders/export" in paths
    assert "/api/v1/analytics/orders/{invoice_id}" in paths

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
        async def get_customer_overview(self, filters, limit, cursor, offset):
            assert cursor is None
            assert offset == 2985
            return CustomerOverviewPage(
                metrics=CustomerOverviewMetrics(
                    total_customers=2,
                    purchasing_customers=1,
                    debtor_customers=1,
                    non_debtor_customers=1,
                    total_revenue=Decimal("7000.00"),
                    invoice_count=3,
                    receivables=Decimal("1200.00"),
                    advances=Decimal("200.00"),
                    net_balance=Decimal("1000.00"),
                    debt_by_ward=(
                        CustomerDebtWardSummary(
                            ward_name="Minh Khai",
                            debtor_customers=1,
                            receivables=Decimal("1200.00"),
                        ),
                    ),
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
            params={
                "date_from": "2025-03-01",
                "date_to": "2025-04-01",
                "offset": 2985,
            },
        )
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["receivables"] == "1200.00"
    assert body["metrics"]["advances"] == "200.00"
    assert body["metrics"]["debtor_customers"] == 1
    assert body["metrics"]["non_debtor_customers"] == 1
    assert body["metrics"]["debt_by_ward"] == [
        {
            "ward_name": "Minh Khai",
            "debtor_customers": 1,
            "receivables": "1200.00",
        }
    ]
    assert body["items"][0]["current_debt"] == "1200.00"
    assert body["next_cursor"] == "next-page-token"
    assert body["has_more"] is True
    assert "offset" not in body


def test_order_list_and_detail_contract_for_staff():
    issued_at = datetime(2025, 3, 20, 9, 30)

    class FakeUseCase:
        async def list_orders(self, filters, limit, offset):
            assert (limit, offset) == (20, 40)
            assert filters.date_from == date(2025, 3, 1)
            assert filters.date_to == date(2025, 4, 1)
            assert filters.invoice_number == "HD-001"
            assert filters.customer_id == "11111111-1111-1111-1111-111111111111"
            assert filters.ward_names == ("Minh Khai",)
            assert filters.village_names == ("Thôn 1",)
            return OrderPage(
                items=(
                    OrderSummary(
                        invoice_id="invoice-id",
                        invoice_number="HD-001",
                        issued_at=issued_at,
                        customer_name="Khách hàng A",
                        customer_ward_name="Minh Khai",
                        customer_village_name="Thôn 1",
                        invoice_total_amount=Decimal("150000.00"),
                        line_count=1,
                    ),
                ),
                total=41,
                limit=limit,
                offset=offset,
            )

        async def get_order_detail(self, invoice_id):
            assert invoice_id == "invoice-id"
            return OrderDetail(
                invoice_id="invoice-id",
                invoice_number="HD-001",
                issued_at=issued_at,
                customer_name="Khách hàng A",
                customer_address_detail="Số 1",
                customer_ward_name="Minh Khai",
                customer_village_name="Thôn 1",
                invoice_total_amount=Decimal("150000.00"),
                lines=(
                    OrderLine(
                        line_number=1,
                        product_name="Sản phẩm A",
                        product_category_name="Nhóm A",
                        unit_name="Cái",
                        unit_price=Decimal("50000.00"),
                        quantity=Decimal("3.000"),
                        line_amount=Decimal("150000.00"),
                    ),
                ),
            )

    container.dashboard_analytics_use_case.override(providers.Object(FakeUseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        client = TestClient(app)
        list_response = client.get(
            "/api/v1/analytics/orders",
            params={
                "date_from": "2025-03-01",
                "date_to": "2025-04-01",
                "invoice_number": " HD-001 ",
                "customer_id": "11111111-1111-1111-1111-111111111111",
                "ward": "Minh Khai",
                "village": "Thôn 1",
                "limit": 20,
                "offset": 40,
            },
        )
        detail_response = client.get("/api/v1/analytics/orders/invoice-id")
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["invoice_number"] == "HD-001"
    assert list_response.json()["total"] == 41
    assert detail_response.status_code == 200
    assert detail_response.json()["lines"][0]["product_name"] == "Sản phẩm A"
    assert detail_response.json()["lines"][0]["quantity"] == "3.000"


def test_order_detail_returns_not_found():
    class FakeUseCase:
        async def get_order_detail(self, invoice_id):
            return None

    container.dashboard_analytics_use_case.override(providers.Object(FakeUseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get("/api/v1/analytics/orders/missing")
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


def test_order_ledger_export_forwards_filters_and_returns_xlsx():
    class FakeExportUseCase:
        received = None

        async def execute(self, filters):
            self.received = filters
            return b"ledger-xlsx"

    fake = FakeExportUseCase()
    container.export_order_ledger_use_case.override(providers.Object(fake))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/orders/export",
            params={
                "date_from": "2025-03-01",
                "date_to": "2025-03-31",
                "invoice_number": " XB ",
                "customer_id": "11111111-1111-1111-1111-111111111111",
                "ward": "Minh Khai",
                "village": "Thôn 1",
            },
        )
    finally:
        container.export_order_ledger_use_case.reset_override()

    assert response.status_code == 200
    assert response.content == b"ledger-xlsx"
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "chi-tiet-giao-dich-cong-no-" in response.headers["content-disposition"]
    assert fake.received.date_from == date(2025, 3, 1)
    assert fake.received.date_to == date(2025, 3, 31)
    assert fake.received.invoice_number == "XB"
    assert fake.received.customer_id == "11111111-1111-1111-1111-111111111111"
    assert fake.received.ward_names == ("Minh Khai",)
    assert fake.received.village_names == ("Thôn 1",)


def test_order_ledger_export_requires_customer():
    class FakeExportUseCase:
        async def execute(self, filters):
            raise AssertionError("The use case must not run without a customer")

    container.export_order_ledger_use_case.override(providers.Object(FakeExportUseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get("/api/v1/analytics/orders/export")
    finally:
        container.export_order_ledger_use_case.reset_override()

    assert response.status_code == 422


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


def test_customer_overview_rejects_cursor_with_offset():
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
                "cursor": "cursor-token",
                "offset": 15,
            },
        )
    finally:
        container.dashboard_analytics_use_case.reset_override()

    assert response.status_code == 422
    assert response.json()["detail"] == "Cursor and offset cannot be used together"


def test_customer_debt_export_forwards_multi_filters_and_returns_xlsx():
    class FakeExportUseCase:
        received = None

        async def execute(self, filters):
            self.received = filters
            return b"xlsx-content"

    fake = FakeExportUseCase()
    container.export_customer_debt_use_case.override(providers.Object(fake))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/customer-debt/export",
            params=[
                ("date_from", "2025-03-01"),
                ("date_to", "2025-03-31"),
                ("ward", "Minh Khai"),
                ("ward", "Phú Diễn"),
                ("customer_id", "11111111-1111-1111-1111-111111111111"),
                ("customer_id", "22222222-2222-2222-2222-222222222222"),
                ("positive_debt_only", "true"),
                ("sheet_mode", "ward"),
            ],
        )
    finally:
        container.export_customer_debt_use_case.reset_override()

    assert response.status_code == 200
    assert response.content == b"xlsx-content"
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "cong-no-khach-hang-" in response.headers["content-disposition"]
    assert fake.received.date_from == date(2025, 3, 1)
    assert fake.received.date_to == date(2025, 3, 31)
    assert fake.received.ward_names == ("Minh Khai", "Phú Diễn")
    assert fake.received.customer_ids == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    assert fake.received.positive_debt_only is True
    assert fake.received.sheet_mode.value == "ward"


def test_customer_debt_export_requires_ward_for_village_sheets():
    class FakeExportUseCase:
        async def execute(self, filters):
            raise AssertionError("The use case must not run for invalid filters")

    container.export_customer_debt_use_case.override(providers.Object(FakeExportUseCase()))
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "staff-id",
            "role": "staff",
        }
        response = TestClient(app).get(
            "/api/v1/analytics/customer-debt/export",
            params={"sheet_mode": "village"},
        )
    finally:
        container.export_customer_debt_use_case.reset_override()

    assert response.status_code == 422
    assert response.json()["detail"] == "Village sheets require at least one ward filter"
