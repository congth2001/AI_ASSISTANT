"""Regression tests for analytics hardening: cursor safety, shared scope, limits, ledger."""
import base64
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from config.container import container
from main import create_app
from src.modules.analytics.application.use_cases.dashboard_analytics_use_case import (
    DashboardAnalyticsUseCase,
)
from src.modules.analytics.domain.errors import (
    CustomerDebtRowLimitError,
    ExportWorkbookRowLimitError,
    InvalidCursorValuesError,
    InvalidCustomerOverviewCursorError,
    OrderLedgerRowLimitError,
)
from src.modules.analytics.domain.models.customer_debt import (
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
    CustomerDebtSheetMode,
)
from src.modules.analytics.domain.models.dashboard import (
    DashboardFilters,
    RankingDimension,
    TimeGrain,
    TimeSeriesPoint,
)
from src.modules.analytics.domain.models.order_ledger import (
    OrderLedgerExportData,
    OrderLedgerExportFilters,
)
from src.modules.analytics.domain.models.orders import OrderFilters
from src.modules.analytics.infrastructure.exporters.customer_debt_workbook_exporter import (
    OpenpyxlCustomerDebtWorkbookExporter,
)
from src.modules.analytics.infrastructure.exporters.order_ledger_workbook_exporter import (
    OpenpyxlOrderLedgerWorkbookExporter,
)
from src.modules.analytics.infrastructure.exporters.xlsx_common import (
    clean_sheet_name,
    truncate_sheet_name,
    write_text,
)
from src.modules.analytics.infrastructure.repositories.analytics_scope import (
    customer_scope,
    revenue_movements,
)
from src.modules.analytics.infrastructure.repositories.dashboard_analytics_repository import (
    DashboardAnalyticsRepository,
)
from src.modules.analytics.infrastructure.repositories.order_ledger_builder import (
    CustomerProfile,
    DocumentLine,
    LedgerEntry,
    build_ledger_items,
)
from src.modules.auth.presentation.router import get_current_user

UUID_A = "11111111-1111-1111-1111-111111111111"


def compile_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def encode(payload) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def good_payload(**overrides):
    payload = {"debt": "10.00", "revenue": "5.00", "label": "Khách", "key": UUID_A}
    payload.update(overrides)
    return payload


# --- 1. cursor hardening -----------------------------------------------------

@pytest.mark.parametrize("payload", [
    good_payload(debt="x"),                   # decimal.InvalidOperation
    good_payload(revenue="1,5"),
    good_payload(debt=12),                    # not a string
    good_payload(key="not-a-uuid"),           # would crash the DB driver later
    good_payload(label=None),
    good_payload(label=["a"]),
    ["debt", "revenue"],                      # payload is not an object
    {"debt": "1"},                            # missing keys
    "text",
    None,
])
def test_cursor_with_corrupt_payload_is_rejected_as_validation_error(payload):
    with pytest.raises(InvalidCustomerOverviewCursorError):
        DashboardAnalyticsUseCase._decode_customer_cursor(encode(payload))


@pytest.mark.parametrize("raw", ["@@@", "", "e30", "bm90LWpzb24"])
def test_cursor_with_corrupt_encoding_is_rejected(raw):
    with pytest.raises(InvalidCustomerOverviewCursorError):
        DashboardAnalyticsUseCase._decode_customer_cursor(raw)


@pytest.mark.parametrize("payload", [
    good_payload(debt="NaN"),
    good_payload(debt="Infinity"),
    good_payload(revenue="1E+30"),            # beyond numeric(18,2)
    good_payload(debt="1E-20"),               # absurd scale
    good_payload(label=""),
])
def test_cursor_with_out_of_range_values_reports_invalid_values(payload):
    with pytest.raises(InvalidCursorValuesError):
        DashboardAnalyticsUseCase._decode_customer_cursor(encode(payload))


def test_cursor_rejects_deeply_nested_json_without_crashing():
    nested = "[" * 700 + "]" * 700
    value = base64.urlsafe_b64encode(nested.encode()).decode().rstrip("=")
    with pytest.raises(InvalidCustomerOverviewCursorError):
        DashboardAnalyticsUseCase._decode_customer_cursor(value)


def test_cursor_validation_error_is_a_422_not_a_500():
    container.dashboard_analytics_use_case.override(
        providers.Object(DashboardAnalyticsUseCase(repository=object()))
    )
    try:
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: {"id": "staff", "role": "staff"}
        client = TestClient(app, raise_server_exceptions=False)
        responses = [
            client.get("/api/v1/analytics/customer-overview", params={
                "date_from": "2025-03-01", "date_to": "2025-04-01", "cursor": encode(payload),
            })
            for payload in (good_payload(debt="x"), good_payload(debt="NaN"))
        ]
    finally:
        container.dashboard_analytics_use_case.reset_override()
    assert [r.status_code for r in responses] == [422, 422]
    assert responses[0].json()["detail"] == "Invalid customer overview cursor"
    assert responses[1].json()["detail"] == "Invalid cursor values"


# --- 13. time-series-comparison grains ----------------------------------------

class DailySeries:
    """Returns one point per day: revenue = day ordinal, so aligned sums are checkable."""

    async def get_time_series(self, filters, grain):
        assert grain == TimeGrain.DAY
        return [
            TimeSeriesPoint(filters.date_from + timedelta(days=i), Decimal(filters.date_from.toordinal() + i), 1)
            for i in range(filters.day_count)
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("grain,start,end,expected_starts", [
    (TimeGrain.WEEK, date(2025, 3, 5), date(2025, 3, 20), [date(2025, 3, 5), date(2025, 3, 10), date(2025, 3, 17)]),
    (TimeGrain.MONTH, date(2025, 1, 25), date(2025, 2, 10), [date(2025, 1, 25), date(2025, 2, 1)]),
    (TimeGrain.QUARTER, date(2025, 3, 25), date(2025, 4, 10), [date(2025, 3, 25), date(2025, 4, 1)]),
    (TimeGrain.YEAR, date(2024, 12, 28), date(2025, 1, 5), [date(2024, 12, 28), date(2025, 1, 1)]),
])
async def test_comparison_buckets_cross_calendar_boundaries(grain, start, end, expected_starts):
    filters = DashboardFilters(start, end)
    result = await DashboardAnalyticsUseCase(DailySeries()).get_time_series_comparison(filters, grain)

    assert [p.period_start for p in result] == expected_starts
    # Buckets tile the period exactly: contiguous, same total day count on both sides.
    assert result[0].period_start == start and result[-1].period_end == end
    previous = filters.previous_period()
    assert result[0].previous_period_start == previous.date_from
    assert result[-1].previous_period_end == previous.date_to
    for left, right in zip(result, result[1:]):
        assert left.period_end == right.period_start
        assert left.previous_period_end == right.previous_period_start
    for point in result:
        days = (point.period_end - point.period_start).days
        assert days == (point.previous_period_end - point.previous_period_start).days
        assert point.invoice_count == days and point.previous_invoice_count == days
        first = point.period_start.toordinal()
        assert point.revenue == sum(Decimal(first + i) for i in range(days))
        previous_first = point.previous_period_start.toordinal()
        assert point.previous_revenue == sum(Decimal(previous_first + i) for i in range(days))
    assert sum(p.invoice_count for p in result) == filters.day_count


# --- 2/3/5. shared customer scope --------------------------------------------

def test_customer_scope_always_excludes_soft_deleted_customers():
    sql = compile_sql(select(1).where(*customer_scope(DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))).conditions()))
    assert "customers.deleted_at IS NULL" in sql
    sql = compile_sql(select(1).where(*customer_scope(DashboardFilters(
        date(2025, 3, 1), date(2025, 4, 1), customer_id=UUID_A, ward_names=("Xã A",), village_names=("Thôn 1",),
    )).conditions()))
    assert f"customers.customer_id = '{UUID_A.replace('-', '')}'" in sql
    assert "customers.ward_name IN ('Xã A')" in sql and "customers.village_name IN ('Thôn 1')" in sql


def test_summary_scope_and_other_fact_queries_use_the_same_customer_semi_join():
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1), ward_names=("Xã A",))
    marker = "IN (SELECT customers.customer_id \nFROM customers \nWHERE customers.deleted_at IS NULL AND customers.ward_name IN ('Xã A'))"
    _, invoice_predicates = DashboardAnalyticsRepository._invoice_scope(filters)
    _, return_predicates = DashboardAnalyticsRepository._sales_return_scope(filters)
    balance = DashboardAnalyticsRepository._customer_debt_balance(filters)
    movements = revenue_movements(filters, filters.date_from, filters.date_to, "m")
    texts = [
        compile_sql(select(1).where(*invoice_predicates)),
        compile_sql(select(1).where(*return_predicates)),
        compile_sql(select(balance)),
        compile_sql(select(movements)),
    ]
    assert all(marker in text for text in texts), texts


def test_customer_revenue_movements_include_returns_and_switch_to_lines_with_filters():
    plain = compile_sql(select(revenue_movements(
        DashboardFilters(date(2025, 3, 1), date(2025, 4, 1)), date(2025, 3, 1), date(2025, 4, 1), "m",
    )))
    assert "sales_invoices.invoice_total_amount" in plain
    assert "customer_debt_transactions.source_type = 'sales_return'" in plain
    assert "sales_invoice_lines" not in plain

    filtered = compile_sql(select(revenue_movements(
        DashboardFilters(date(2025, 3, 1), date(2025, 4, 1), product_names=("Gạch",)),
        date(2025, 3, 1), date(2025, 4, 1), "m",
    )))
    assert "sales_invoice_lines.line_amount" in filtered
    assert "-sales_return_lines.line_amount" in filtered
    assert "sales_invoice_lines.product_name IN ('Gạch')" in filtered
    assert "sales_return_lines.product_name IN ('Gạch')" in filtered
    assert "invoice_total_amount" not in filtered
    assert "source_type" not in filtered


def test_customer_ranking_and_overview_share_movements_and_do_not_inner_join_invoices():
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))
    ranking = compile_sql(DashboardAnalyticsRepository(None)._ranking_statement(filters, RankingDimension.CUSTOMER))
    overview = compile_sql(select(DashboardAnalyticsRepository._customer_period_activity(filters)))
    for sql in (ranking, overview):
        assert "UNION ALL" in sql and "sales_return" in sql  # return-only customers are included
    assert "JOIN sales_invoices" not in ranking


@pytest.mark.parametrize("dimension", list(RankingDimension))
@pytest.mark.asyncio
async def test_ranking_orders_by_key_last_for_stable_offset_paging(dimension):
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

    class Context:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    repository = DashboardAnalyticsRepository(lambda: Context())
    await repository.get_ranking(DashboardFilters(date(2025, 3, 1), date(2025, 4, 1)), dimension, 10, 20)
    order_by = compile_sql(captured[1]).split("ORDER BY")[-1]
    assert "revenue DESC" in order_by and "label ASC" in order_by
    assert order_by.index("label ASC") < order_by.index("key ASC")
    assert "LIMIT 10 OFFSET 20" in order_by


def test_customer_overview_pushes_scope_into_ledger_and_period_subqueries():
    filters = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1), ward_names=("Xã A",))
    sql = compile_sql(select(DashboardAnalyticsRepository._customer_overview_subquery(filters)))
    # Customer scope inside the balance and movement subqueries, not only on the outer customer.
    assert sql.count("customers.ward_name IN ('Xã A')") >= 4


@pytest.mark.asyncio
async def test_customer_overview_runs_two_statements_not_three():
    captured = []

    class Result:
        def all(self):
            return []

    class Session:
        async def execute(self, statement):
            captured.append(statement)
            return Result()

    class Context:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    metrics, items, total, has_more = await DashboardAnalyticsRepository(lambda: Context()).get_customer_overview(
        DashboardFilters(date(2025, 3, 1), date(2025, 4, 1)), 10, None,
    )
    assert len(captured) == 2
    assert (metrics.total_customers, metrics.receivables, items, total, has_more) == (0, Decimal(0), [], 0, False)


# --- 6. list_orders line counts ----------------------------------------------

@pytest.mark.asyncio
async def test_list_orders_counts_lines_after_pagination_instead_of_grouping_all_lines():
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

    class Context:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    await DashboardAnalyticsRepository(lambda: Context()).list_orders(OrderFilters(), 20, 40)
    sql = compile_sql(captured[1])
    assert "GROUP BY" not in sql
    # LIMIT/OFFSET are applied inside ``order_page``; lines are counted per page row only.
    assert "LIMIT 20 OFFSET 40) AS order_page" in sql
    assert "sales_invoice_lines.invoice_id = order_page.invoice_id" in sql


# --- 9. filter options --------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_options_escape_like_wildcards_for_every_search():
    captured = []

    class Result:
        @staticmethod
        def all():
            return []

        @staticmethod
        def scalars():
            return Result()

    class Session:
        async def execute(self, statement):
            captured.append(statement)
            return Result()

    class Context:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    await DashboardAnalyticsRepository(lambda: Context()).get_filter_options("100%_x", 10)
    sql = "\n".join(compile_sql(statement) for statement in captured)
    # The driver doubles '%' in this rendering: 100/%%/_x is the escaped literal "100%_x".
    assert sql.count("'100/%%/_x'") >= 7 and sql.count("ESCAPE '/'") >= 7
    assert "'%100%_x%'" not in sql


def _client(role="staff"):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": "staff", "role": role}
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path,param", [
    ("filter-options", "ward"), ("filter-options", "village"),
    ("summary", "ward"), ("summary", "village"), ("summary", "category"), ("summary", "product"),
    ("orders", "ward"), ("orders", "village"),
])
def test_repeated_filter_parameters_are_capped_at_100_values(path, param):
    params = [("date_from", "2025-03-01"), ("date_to", "2025-04-01")] + [(param, f"v{i}") for i in range(101)]
    response = _client().get(f"/api/v1/analytics/{path}", params=params)
    assert response.status_code == 422
    assert response.json()["detail"] == f"'{param}' accepts at most 100 values"


def test_filter_value_length_is_capped():
    response = _client().get("/api/v1/analytics/summary", params={
        "date_from": "2025-03-01", "date_to": "2025-04-01", "ward": "x" * 201,
    })
    assert response.status_code == 422


def test_exactly_100_values_are_accepted():
    class UseCase:
        async def get_filter_options(self, search, limit, ward_names=(), village_names=()):
            from src.modules.analytics.domain.models.dashboard import DashboardFilterOptions
            assert len(ward_names) == 100
            return DashboardFilterOptions((), (), (), (), ())

    container.dashboard_analytics_use_case.override(providers.Object(UseCase()))
    try:
        response = _client().get("/api/v1/analytics/filter-options", params=[("ward", f"w{i}") for i in range(100)])
    finally:
        container.dashboard_analytics_use_case.reset_override()
    assert response.status_code == 200


# --- 10. router only maps validation errors -----------------------------------

def test_infrastructure_failures_are_not_disguised_as_validation_errors():
    class Boom(Exception):
        pass

    class UseCase:
        async def get_customer_overview(self, *args):
            raise ValueError("driver exploded")  # a plain ValueError is a bug, not bad input

    container.dashboard_analytics_use_case.override(providers.Object(UseCase()))
    try:
        response = _client().get("/api/v1/analytics/customer-overview", params={
            "date_from": "2025-03-01", "date_to": "2025-04-01",
        })
    finally:
        container.dashboard_analytics_use_case.reset_override()
    assert response.status_code == 500


def test_missing_customer_in_ledger_export_is_404_not_422():
    from src.modules.analytics.domain.errors import CustomerNotFoundError

    class UseCase:
        async def execute(self, filters):
            raise CustomerNotFoundError()

    container.export_order_ledger_use_case.override(providers.Object(UseCase()))
    try:
        response = _client().get("/api/v1/analytics/orders/export", params={"customer_id": UUID_A})
    finally:
        container.export_order_ledger_use_case.reset_override()
    assert response.status_code == 404


def test_row_limit_errors_remain_422():
    class UseCase:
        async def execute(self, filters):
            raise OrderLedgerRowLimitError(max_rows=10)

    container.export_order_ledger_use_case.override(providers.Object(UseCase()))
    try:
        response = _client().get("/api/v1/analytics/orders/export", params={"customer_id": UUID_A})
    finally:
        container.export_order_ledger_use_case.reset_override()
    assert response.status_code == 422
    assert "10 rows" in response.json()["detail"]


# --- 7. ledger assembly --------------------------------------------------------

D = datetime
PROFILE = {"c1": CustomerProfile("c1", "Khách A", "Địa chỉ")}


def sale_line(doc, number, at, total, line, product="Gạch", customer="c1"):
    return DocumentLine(doc, number, at, customer, Decimal(total), None, line, product, "Cái", Decimal(10), Decimal(1))


def entry(kind, source_id, at, amount, customer="c1"):
    return LedgerEntry(customer, kind, source_id, at, Decimal(amount))


def build(**kw):
    defaults = dict(profiles=PROFILE, opening_balances={}, entries=[], sale_lines=[], return_lines=[])
    defaults.update(kw)
    return build_ledger_items(**defaults)


def test_ledger_running_balance_is_the_signed_ledger_not_invoice_debt_delta():
    items = build(
        opening_balances={"c1": Decimal("1000")},
        entries=[
            entry("sale", "legacy-1", D(2025, 3, 5, 9), "300"),
            entry("receipt", "PT1", D(2025, 3, 6, 9), "-100"),
            entry("sales_return", "src-NT1", D(2025, 3, 7, 9), "-40"),
        ],
        sale_lines=[sale_line("i1", "XB1", D(2025, 3, 5, 9), "500", 1), sale_line("i1", "XB1", D(2025, 3, 5, 9), "500", 2, "Xi măng")],
        return_lines=[DocumentLine("r1", "NT1", D(2025, 3, 7, 9), "c1", Decimal("40"), "src-NT1", 1, "Gạch", "Cái", Decimal(10), Decimal(4))],
    )
    assert [i.running_debt for i in items] == [1300, 1300, 1200, 1160]
    first = items[0]
    assert first.debt_amount == 300 and first.payment_amount == 200  # 500 total - 300 on credit
    assert items[1].debt_amount == 0 and items[1].payment_amount == 0  # later line of same invoice
    assert items[2].reason == "Thu nợ" and items[2].payment_amount == 100
    assert items[3].reason == "Nhập trả" and items[3].debt_amount == -40


def test_fully_paid_invoice_without_ledger_row_has_zero_movement_and_ledger_only_rows_are_kept():
    items = build(
        opening_balances={"c1": Decimal("50")},
        entries=[entry("sale", "no-doc", D(2025, 3, 9), "20"), entry("sales_return", "src-X", D(2025, 3, 10), "-5")],
        sale_lines=[sale_line("i1", "XB1", D(2025, 3, 5), "80", 1)],
    )
    by_voucher = {i.voucher_number: i for i in items}
    assert by_voucher["XB1"].payment_amount == 80 and by_voucher["XB1"].running_debt == 50
    assert by_voucher["no-doc"].debt_amount == 20 and by_voucher["no-doc"].running_debt == 70
    assert by_voucher["src-X"].reason == "Nhập trả" and by_voucher["src-X"].running_debt == 65
    assert items[-1].running_debt == 65  # == opening + all ledger movements


def test_two_invoices_at_same_instant_attribute_the_ledger_amount_once():
    items = build(
        entries=[entry("sale", "a", D(2025, 3, 5), "30"), entry("sale", "b", D(2025, 3, 5), "70")],
        sale_lines=[sale_line("i2", "XB2", D(2025, 3, 5), "70", 1), sale_line("i1", "XB1", D(2025, 3, 5), "30", 1)],
    )
    assert sum(i.debt_amount for i in items) == 100 and items[-1].running_debt == 100


def test_voucher_filter_hides_rows_but_keeps_balance_from_hidden_rows():
    items = build(
        entries=[entry("sale", "a", D(2025, 3, 5), "30"), entry("receipt", "PT9", D(2025, 3, 6), "-10")],
        sale_lines=[sale_line("i1", "XB1", D(2025, 3, 5), "30", 1)],
        invoice_search="pt9",
    )
    assert [i.voucher_number for i in items] == ["PT9-0325"] and items[0].running_debt == 20


# --- 8. exporters -------------------------------------------------------------

def debt_item(label, ward="Xã A", village="Thôn A", debt="1"):
    return CustomerDebtExportItem(label, label, ward, village, "Địa chỉ", Decimal(debt))


def test_debt_export_limits_are_checked_before_any_workbook_is_built(monkeypatch):
    exporter = OpenpyxlCustomerDebtWorkbookExporter()
    monkeypatch.setattr(OpenpyxlCustomerDebtWorkbookExporter, "MAX_DATA_ROWS", 3)
    monkeypatch.setattr(OpenpyxlCustomerDebtWorkbookExporter, "MAX_TOTAL_ROWS", 5)
    monkeypatch.setattr(exporter, "_register_styles", lambda wb: pytest.fail("workbook must not be created"))

    with pytest.raises(CustomerDebtRowLimitError) as sheet_error:
        exporter.build([debt_item(f"K{i}") for i in range(4)], CustomerDebtExportFilters())
    assert "3 rows" in sheet_error.value.message
    with pytest.raises(ExportWorkbookRowLimitError):  # 3 rows x (All + ward sheet) = 6 > 5
        exporter.build([debt_item(f"K{i}") for i in range(3)], CustomerDebtExportFilters(sheet_mode=CustomerDebtSheetMode.WARD))


def test_debt_export_default_ceilings_are_below_excel_limit():
    assert OpenpyxlCustomerDebtWorkbookExporter.MAX_DATA_ROWS == 200_000
    assert OpenpyxlCustomerDebtWorkbookExporter.MAX_TOTAL_ROWS == 500_000
    assert OpenpyxlOrderLedgerWorkbookExporter.MAX_DATA_ROWS == 200_000


def test_ledger_export_limit_checked_before_building(monkeypatch):
    monkeypatch.setattr(OpenpyxlOrderLedgerWorkbookExporter, "MAX_DATA_ROWS", 1)
    data = OrderLedgerExportData("c1", "Khách", None, items=tuple(
        build(entries=[entry("receipt", "A", D(2025, 3, 1), "-1"), entry("receipt", "B", D(2025, 3, 2), "-1")])
    ))
    with pytest.raises(OrderLedgerRowLimitError):
        OpenpyxlOrderLedgerWorkbookExporter().build(data, OrderLedgerExportFilters())


@pytest.mark.parametrize("text,prefixed", [
    ("=SUM(A1)", True), ("+1", True), ("-5kg", True), ("@cmd", True),
    ("\tTab", True), ("\rReturn", True), ("Bình thường", False), ("", False),
])
def test_write_text_stores_literal_strings_without_changing_visible_value(text, prefixed):
    sheet = Workbook().active
    write_text(sheet["A1"], text)
    assert sheet["A1"].data_type == "s"
    assert sheet["A1"].value == text
    assert bool(sheet["A1"].quotePrefix) is prefixed


def test_exported_formula_like_text_survives_a_round_trip_as_text():
    content = OpenpyxlCustomerDebtWorkbookExporter().build(
        [debt_item("=1+1", ward="-5kg", village="@x")], CustomerDebtExportFilters(),
    )
    sheet = load_workbook(__import__("io").BytesIO(content)).active
    assert [sheet["B5"].value, sheet["C5"].value, sheet["D5"].value] == ["=1+1", "-5kg", "@x"]
    assert all(sheet[f"{c}5"].data_type == "s" for c in "BCD")


@pytest.mark.parametrize("raw,expected", [
    ("'Khách'", "Khách"), ("  'x'  ", "x"), ("A/B:C*D?E[F]G\\H", "A-B-C-D-E-F-G-H"),
    ("'''", "Sheet"), ("", "Sheet"), ("Line\nBreak", "Line-Break"),
])
def test_sheet_name_cleaning(raw, expected):
    assert clean_sheet_name(raw, fallback="Sheet") == expected


def test_sheet_name_truncation_never_leaves_edge_apostrophe_or_reserved_name():
    assert truncate_sheet_name("x" * 30 + "' tail") == "x" * 30
    assert truncate_sheet_name("History") == "History_"
    assert len(truncate_sheet_name("a" * 100)) == 31


def test_debt_export_sheet_names_are_excel_safe_and_unique():
    items = [
        debt_item("K1", ward="'Xã đầu", village="Thôn: 1"),
        debt_item("K2", ward="X" * 28 + "' tail", village="Thôn: 1"),
        debt_item("K3", ward="x" * 28 + "' other", village="Thôn: 1"),
    ]
    content = OpenpyxlCustomerDebtWorkbookExporter().build(
        items, CustomerDebtExportFilters(ward_names=("a",), sheet_mode=CustomerDebtSheetMode.WARD),
    )
    names = load_workbook(__import__("io").BytesIO(content)).sheetnames
    assert len({n.casefold() for n in names}) == len(names)
    assert all(len(n) <= 31 and not n.startswith("'") and not n.endswith("'") for n in names)
    assert "Xã đầu" in names


def test_ledger_sheet_name_drops_edge_apostrophes_and_forbidden_characters():
    assert OpenpyxlOrderLedgerWorkbookExporter._sheet_name("'Ông/Bà: A'") == "Ông Bà  A_DoiTac"
    assert OpenpyxlOrderLedgerWorkbookExporter._sheet_name("'''") == "DoiTac_DoiTac"
    assert len(OpenpyxlOrderLedgerWorkbookExporter._sheet_name("N" * 50)) == 31


def test_debt_export_sets_a_single_autofilter_range():
    content = OpenpyxlCustomerDebtWorkbookExporter().build([debt_item("K1"), debt_item("K2")], CustomerDebtExportFilters())
    sheet = load_workbook(__import__("io").BytesIO(content)).active
    assert sheet.auto_filter.ref == "A4:F6"


def test_debt_export_reuses_named_styles_instead_of_one_style_object_per_cell():
    content = OpenpyxlCustomerDebtWorkbookExporter().build(
        [debt_item(f"K{i}") for i in range(50)], CustomerDebtExportFilters(),
    )
    workbook = load_workbook(__import__("io").BytesIO(content))
    assert len(workbook._fonts) < 12 and len(workbook._cell_styles) < 20
