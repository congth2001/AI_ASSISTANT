from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from src.application.use_cases.dashboard_analytics_use_case import (
    DashboardAnalyticsUseCase,
)
from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardMetricSnapshot,
    CustomerOverviewCursor,
    CustomerDebtExportFilters,
    OrderFilters,
    RankingDimension,
)
from src.infrastructure.repositories.dashboard_analytics_repository import (
    DashboardAnalyticsRepository,
)
from src.infrastructure.repositories.models import CustomerDebtTransaction, SalesInvoice


class FakeDashboardRepository:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.received_filters = []

    async def get_metric_snapshot(self, filters):
        self.received_filters.append(filters)
        return self.snapshots.pop(0)

    async def get_time_series(self, filters, grain):
        return []

    async def get_ranking(self, filters, dimension, limit, offset):
        return [], 0

    async def get_filter_options(
        self, search, limit, ward_names=(), village_names=()
    ):
        self.filter_option_args = {
            "search": search,
            "limit": limit,
            "ward_names": ward_names,
            "village_names": village_names,
        }
        return DashboardFilterOptions((), (), (), (), ())


def snapshot(revenue: str) -> DashboardMetricSnapshot:
    return DashboardMetricSnapshot(
        total_revenue=Decimal(revenue),
        invoice_count=2,
        customer_count=1,
        average_invoice_value=Decimal(revenue) / 2,
        net_debt_delta=Decimal("0"),
    )


def test_filters_use_closed_open_range_and_equal_previous_period():
    filters = DashboardFilters(
        date_from=date(2025, 3, 1),
        date_to=date(2025, 4, 1),
        category_names=("Gạch",),
    )

    previous = filters.previous_period()

    assert filters.day_count == 31
    assert previous.date_from == date(2025, 1, 29)
    assert previous.date_to == date(2025, 3, 1)
    assert previous.category_names == ("Gạch",)


def test_filters_reject_empty_or_reversed_ranges():
    with pytest.raises(ValueError, match="date_from must be before date_to"):
        DashboardFilters(date(2025, 3, 1), date(2025, 3, 1))
    with pytest.raises(ValueError, match="date_from must be before date_to"):
        DashboardFilters(date(2025, 4, 1), date(2025, 3, 1))


@pytest.mark.asyncio
async def test_summary_compares_equal_length_period_and_keeps_decimal_math():
    repository = FakeDashboardRepository(
        [snapshot("7000.00"), snapshot("5200.00")]
    )
    use_case = DashboardAnalyticsUseCase(repository)
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))

    result = await use_case.get_summary(filters)

    assert result.current.total_revenue == Decimal("7000.00")
    assert result.previous_revenue == Decimal("5200.00")
    assert result.revenue_change == Decimal("1800.00")
    assert result.revenue_growth_percent == Decimal("34.62")
    assert repository.received_filters[1] == filters.previous_period()


@pytest.mark.asyncio
async def test_summary_returns_null_growth_when_previous_revenue_is_zero():
    use_case = DashboardAnalyticsUseCase(
        FakeDashboardRepository([snapshot("100.00"), snapshot("0.00")])
    )

    result = await use_case.get_summary(
        DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))
    )

    assert result.revenue_change == Decimal("100.00")
    assert result.revenue_growth_percent is None


def _compile(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_invoice_metric_scope_enforces_soft_delete_time_boundary_and_exists():
    filters = DashboardFilters(
        date(2025, 3, 1),
        date(2025, 4, 1),
        category_names=("Gạch",),
    )
    from_clause, predicates = DashboardAnalyticsRepository._invoice_scope(filters)
    statement = (
        select(func.sum(SalesInvoice.invoice_total_amount))
        .select_from(from_clause)
        .where(*predicates)
    )

    sql = _compile(statement)

    assert "sales_invoices.deleted_at IS NULL" in sql
    assert "sales_invoices.issued_at >= '2025-03-01'" in sql
    assert "sales_invoices.issued_at < '2025-04-01'" in sql
    assert "EXISTS (SELECT 1" in sql
    assert "sales_invoice_lines.deleted_at IS NULL" in sql
    assert "sales_invoice_lines.product_category_name IN ('Gạch')" in sql
    assert "JOIN sales_invoice_lines" not in sql


def test_sales_return_scope_only_uses_active_returns_in_same_period():
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))
    from_clause, predicates = DashboardAnalyticsRepository._sales_return_scope(filters)
    statement = select(func.sum(CustomerDebtTransaction.amount)).select_from(
        from_clause
    ).where(*predicates)

    sql = _compile(statement)

    assert "customer_debt_transactions.deleted_at IS NULL" in sql
    assert "customer_debt_transactions.source_type = 'sales_return'" in sql
    assert "customer_debt_transactions.occurred_at >= '2025-03-01'" in sql
    assert "customer_debt_transactions.occurred_at < '2025-04-01'" in sql


def test_customer_overview_debt_uses_full_signed_ledger_until_period_end():
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))
    balance = DashboardAnalyticsRepository._customer_debt_balance(filters)

    sql = _compile(select(balance))

    assert "sum(customer_debt_transactions.amount)" in sql
    assert "customer_debt_transactions.deleted_at IS NULL" in sql
    assert "customer_debt_transactions.occurred_at < '2025-04-01'" in sql
    assert "customer_debt_transactions.occurred_at >=" not in sql
    assert "sales_invoices.debt_delta_amount" not in sql


def test_customer_overview_revenue_subtracts_returns_in_selected_period():
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))
    returns = DashboardAnalyticsRepository._customer_return_activity(filters)

    sql = _compile(select(returns))

    assert "sum(customer_debt_transactions.amount)" in sql
    assert "customer_debt_transactions.source_type = 'sales_return'" in sql
    assert "customer_debt_transactions.occurred_at >= '2025-03-01'" in sql
    assert "customer_debt_transactions.occurred_at < '2025-04-01'" in sql


@pytest.mark.asyncio
async def test_customer_debt_export_query_uses_inclusive_dates_and_multi_filters():
    captured = []

    class Result:
        @staticmethod
        def all():
            return []

    class Session:
        async def execute(self, statement):
            captured.append(statement)
            return Result()

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    repository = DashboardAnalyticsRepository(session_factory=lambda: SessionContext())
    await repository.get_customer_debt_export(
        CustomerDebtExportFilters(
            date_from=date(2025, 3, 1),
            date_to=date(2025, 3, 31),
            customer_ids=("11111111-1111-1111-1111-111111111111",),
            ward_names=("Minh Khai", "Phú Diễn"),
            positive_debt_only=True,
        )
    )

    sql = _compile(captured[0])
    assert "customer_debt_transactions.occurred_at >= '2025-03-01'" in sql
    assert "customer_debt_transactions.occurred_at < '2025-04-01'" in sql
    assert "customers.customer_id IN (" in sql
    assert "customers.ward_name IN ('Minh Khai', 'Phú Diễn')" in sql
    assert "coalesce(customer_debt_export_balance.current_debt, 0) > 0" in sql
    assert "ORDER BY coalesce(customer_debt_export_balance.current_debt, 0) DESC" in sql


def test_customer_overview_cursor_round_trip_preserves_decimal_and_unicode():
    cursor = CustomerOverviewCursor(
        current_debt=Decimal("1200.50"),
        revenue=Decimal("7000.25"),
        label="Khách hàng Ánh",
        key="customer-id",
    )

    encoded = DashboardAnalyticsUseCase._encode_customer_cursor(cursor)

    assert DashboardAnalyticsUseCase._decode_customer_cursor(encoded) == cursor


@pytest.mark.asyncio
async def test_order_list_query_applies_filters_before_pagination():
    captured = []

    class Result:
        @staticmethod
        def scalar_one():
            return 0

        @staticmethod
        def all():
            return []

    class Session:
        async def execute(self, statement):
            captured.append(statement)
            return Result()

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    repository = DashboardAnalyticsRepository(session_factory=lambda: SessionContext())
    await repository.list_orders(
        OrderFilters(
            date_from=date(2025, 3, 1),
            date_to=date(2025, 4, 1),
            invoice_number="HD-001",
            customer_id="11111111-1111-1111-1111-111111111111",
            ward_names=("Minh Khai",),
            village_names=("Thôn 1",),
        ),
        20,
        40,
    )

    sql = _compile(captured[1])
    assert "sales_invoices.issued_at >= '2025-03-01'" in sql
    assert "sales_invoices.issued_at < '2025-04-01'" in sql
    assert "sales_invoices.invoice_number" in sql and "HD-001" in sql
    assert "sales_invoices.customer_id =" in sql
    assert "sales_invoices.customer_ward_name_snapshot IN ('Minh Khai')" in sql
    assert "sales_invoices.customer_village_name_snapshot IN ('Thôn 1')" in sql
    assert "LIMIT 20 OFFSET 40" in sql


def test_customer_overview_rejects_invalid_cursor():
    with pytest.raises(ValueError, match="Invalid customer overview cursor"):
        DashboardAnalyticsUseCase._decode_customer_cursor("not-a-valid-cursor")


def test_product_ranking_uses_line_revenue_and_groups_quantity_by_unit():
    repository = DashboardAnalyticsRepository(session_factory=None)
    statement = repository._ranking_statement(
        DashboardFilters(date(2025, 1, 1), date(2025, 4, 1)),
        RankingDimension.PRODUCT,
    )

    sql = _compile(statement)

    assert "UNION ALL" in sql
    assert "sales_return_lines.line_amount" in sql
    assert "-sales_return_lines.line_amount" in sql
    assert "sales_return_lines.quantity" in sql
    assert "sales_invoice_lines.deleted_at IS NULL" in sql
    assert "sales_invoices.deleted_at IS NULL" in sql
    assert "sales_returns.returned_at >= '2025-01-01'" in sql
    assert "GROUP BY product_movements.key, product_movements.label, product_movements.unit_name" in sql
    assert "sum(sales_invoices.invoice_total_amount)" not in sql


@pytest.mark.asyncio
async def test_filter_options_forward_dependent_geography_filters():
    repository = FakeDashboardRepository([])
    use_case = DashboardAnalyticsUseCase(repository)

    await use_case.get_filter_options(
        "  An Phát  ",
        25,
        ward_names=("Minh Khai",),
        village_names=("Thôn 1",),
    )

    assert repository.filter_option_args == {
        "search": "An Phát",
        "limit": 25,
        "ward_names": ("Minh Khai",),
        "village_names": ("Thôn 1",),
    }
