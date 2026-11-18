"""Opt-in PostgreSQL checks that summary, rankings and customer overview agree.

Run with AI_ANALYTICS_TEST_DSN (for example
``postgresql+asyncpg://postgres@localhost:55432/postgres``) or AI_ANALYTICS_LOCAL_DB_TEST=1.
Every test works inside one transaction in a throw-away schema built from the real ORM
models; nothing is committed and no public table is touched.
"""
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.config_manager import get_database_settings
from src.common.infrastructure.database.base import Base
from src.modules.analytics.domain.models.customer_debt import CustomerDebtExportFilters, CustomerOverviewCursor
from src.modules.analytics.domain.models.dashboard import DashboardFilters, RankingDimension, TimeGrain
from src.modules.analytics.domain.models.order_ledger import OrderLedgerExportFilters
from src.modules.analytics.domain.models.orders import OrderFilters
from src.modules.analytics.infrastructure.repositories.dashboard_analytics_repository import (
    DashboardAnalyticsRepository,
)
from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtTransaction,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)

TABLES = [m.__table__ for m in (
    Customer, SalesInvoice, SalesInvoiceLine, SalesReturn, SalesReturnLine, CustomerDebtTransaction,
)]


def cid(number: int) -> str:
    return f"00000000-0000-0000-0000-{number:012d}"


A, B, C, D, E, F = (cid(i) for i in range(1, 7))
FILTERS = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1))
GACH = DashboardFilters(date(2025, 3, 1), date(2025, 4, 1), product_names=("Gạch",))


@pytest_asyncio.fixture
async def repository():
    dsn = os.getenv("AI_ANALYTICS_TEST_DSN")
    if not dsn and os.getenv("AI_ANALYTICS_LOCAL_DB_TEST") != "1":
        pytest.skip("Set AI_ANALYTICS_LOCAL_DB_TEST=1 or AI_ANALYTICS_TEST_DSN")
    engine = create_async_engine(dsn or get_database_settings().sqlalchemy_url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            schema = f"analytics_it_{uuid.uuid4().hex[:8]}"
            await connection.execute(text(f"CREATE SCHEMA {schema}"))
            await connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=TABLES))
            async with AsyncSession(bind=connection) as session:
                await _seed(session)
                await session.flush()
            yield DashboardAnalyticsRepository(lambda: AsyncSession(bind=connection)), connection
            await transaction.rollback()
    finally:
        await engine.dispose()


def customer(customer_id, name, ward, deleted=False):
    return Customer(
        customer_id=customer_id, customer_identity_key=f"{name}|{customer_id}", customer_name=name,
        ward_name=ward, village_name="Thôn 1", address_detail=f"Địa chỉ {name}",
        deleted_at=datetime(2025, 3, 6) if deleted else None,
    )


def invoice(number, customer_id, day, total, lines, debt=None):
    inv = SalesInvoice(
        invoice_id=f"id-{number}", invoice_number=number, issued_at=datetime.fromisoformat(day),
        customer_id=customer_id, customer_name_snapshot="snap", invoice_total_amount=Decimal(total),
        debt_delta_amount=None if debt is None else Decimal(debt),
    )
    return inv, [
        SalesInvoiceLine(
            invoice_line_id=f"id-{number}-{i}", invoice_id=inv.invoice_id, line_number=i,
            product_name=product, product_category_name=category, unit_name="Cái",
            unit_price=Decimal(amount), quantity=Decimal(1), line_amount=Decimal(amount),
        )
        for i, (product, category, amount) in enumerate(lines, 1)
    ]


def sales_return(number, customer_id, day, product, category, amount):
    ret = SalesReturn(
        return_id=f"ret-{number}", source_id=f"src-{number}", return_number=number,
        returned_at=datetime.fromisoformat(day), customer_id=customer_id,
        customer_name_snapshot="snap", return_total_amount=Decimal(amount),
    )
    return ret, SalesReturnLine(
        return_line_id=f"ret-{number}-1", return_id=ret.return_id, source_line_id="1", line_number=1,
        product_name=product, product_category_name=category, unit_name="Cái",
        unit_price=Decimal(amount), quantity=Decimal(1), line_amount=Decimal(amount),
    )


def ledger(customer_id, kind, source_id, day, amount):
    return CustomerDebtTransaction(
        debt_transaction_id=str(uuid.uuid4()), customer_id=customer_id, source_type=kind,
        source_id=source_id, occurred_at=datetime.fromisoformat(day), amount=Decimal(amount),
    )


async def _seed(session: AsyncSession) -> None:
    session.add_all([
        customer(A, "Khách A", "Xã 1"), customer(B, "Khách B", "Xã 1"),
        customer(C, "Khách C", "Xã 2"), customer(D, "Khách D", "Xã 2", deleted=True),
        customer(E, "Khách Trùng", "Xã 2"), customer(F, "Khách Trùng", "Xã 2"),
    ])
    await session.flush()
    rows = [
        invoice("XB-A0", A, "2025-02-10", "70", [("Gạch", "VLXD", "70")]),
        invoice("XB-A1", A, "2025-03-05", "300", [("Gạch", "VLXD", "200"), ("Xi măng", "VLXD", "100")], "300"),
        invoice("XB-A2", A, "2025-03-10", "100", [("Gạch", "VLXD", "100")], "60"),
        invoice("XB-B1", B, "2025-03-06", "50", [("Xi măng", "VLXD", "50")], "50"),
        invoice("XB-D1", D, "2025-03-07", "500", [("Gạch", "VLXD", "500")], "500"),
        invoice("XB-E1", E, "2025-03-08", "10", [("Gạch", "VLXD", "10")], "10"),
        invoice("XB-F1", F, "2025-03-08", "10", [("Gạch", "VLXD", "10")], "10"),
    ]
    for inv, lines in rows:
        session.add(inv)
    await session.flush()
    for _, lines in rows:
        session.add_all(lines)
    returns = [
        sales_return("NT-A", A, "2025-03-12", "Gạch", "VLXD", "40"),
        sales_return("NT-C", C, "2025-03-15", "Xi măng", "VLXD", "25"),
    ]
    for ret, _ in returns:
        session.add(ret)
    await session.flush()
    session.add_all([line for _, line in returns])
    session.add_all([
        ledger(A, "opening", A, "2025-01-01", "1000"), ledger(C, "opening", C, "2025-01-01", "100"),
        ledger(A, "sale", "legacy-A1", "2025-03-05", "300"), ledger(A, "sale", "legacy-A2", "2025-03-10", "60"),
        ledger(B, "sale", "legacy-B1", "2025-03-06", "50"), ledger(D, "sale", "legacy-D1", "2025-03-07", "500"),
        ledger(E, "sale", "legacy-E1", "2025-03-08", "10"), ledger(F, "sale", "legacy-F1", "2025-03-08", "10"),
        ledger(A, "sales_return", "src-NT-A", "2025-03-12", "-40"), ledger(C, "sales_return", "src-NT-C", "2025-03-15", "-25"),
        ledger(A, "receipt", "PT001", "2025-03-20", "-150"),
        ledger(A, "sale", "legacy-orphan", "2025-03-25", "20"),
    ])


@pytest.mark.asyncio
async def test_summary_ranking_and_customer_overview_agree_without_filters(repository):
    repo, _ = repository
    summary = await repo.get_metric_snapshot(FILTERS)
    ranking, total = await repo.get_ranking(FILTERS, RankingDimension.CUSTOMER, 10, 0)
    metrics, items, overview_total, _ = await repo.get_customer_overview(FILTERS, 10, None)

    # Soft-deleted customer D (500) is excluded everywhere; return-only customer C counts.
    assert summary.total_revenue == Decimal("405")
    assert summary.invoice_count == 5 and summary.customer_count == 4
    assert sum(item.revenue for item in ranking) == summary.total_revenue
    assert metrics.total_revenue == summary.total_revenue
    assert {item.label: item.revenue for item in ranking if item.label != "Khách Trùng"} == {
        "Khách A": Decimal("360"), "Khách B": Decimal("50"), "Khách C": Decimal("-25"),
    }
    assert total == 5 and overview_total == 5
    assert [i.key for i in ranking] == [A, B, E, F, C]  # tie on revenue+label resolved by key
    revenue_by_customer = {i.key: i.revenue for i in items}
    assert revenue_by_customer[C] == Decimal("-25")
    assert {i.key: i.revenue for i in ranking} == {k: v for k, v in revenue_by_customer.items()}


@pytest.mark.asyncio
async def test_product_filter_uses_line_revenue_consistently(repository):
    repo, _ = repository
    summary = await repo.get_metric_snapshot(GACH)
    ranking, _ = await repo.get_ranking(GACH, RankingDimension.CUSTOMER, 10, 0)
    metrics, items, _, _ = await repo.get_customer_overview(GACH, 10, None)
    series = await repo.get_time_series(GACH, TimeGrain.MONTH)

    # Gạch lines 200+100+10+10 minus the 40 returned = 280 (invoice totals would give 470+).
    assert summary.total_revenue == Decimal("280")
    assert metrics.total_revenue == Decimal("280")
    assert sum(i.revenue for i in ranking) == Decimal("280")
    assert sum(point.revenue for point in series) == Decimal("280")
    by_key = {i.key: i for i in items}
    assert by_key[A].revenue == Decimal("260") and by_key[A].invoice_count == 2
    assert by_key[B].revenue == Decimal("0") and by_key[B].invoice_count == 0
    assert by_key[C].revenue == Decimal("0")  # her return is cement, not tiles
    assert [i.key for i in ranking] == [A, E, F]
    # The ledger has no product grain: debt figures ignore the filter.
    assert by_key[A].current_debt == Decimal("1190")
    assert metrics.receivables == Decimal("1190") + 50 + 75 + 10 + 10


@pytest.mark.asyncio
async def test_customer_overview_metrics_and_cursor_paging(repository):
    repo, _ = repository
    metrics, items, total, has_more = await repo.get_customer_overview(FILTERS, 2, None)
    assert total == 5 and has_more
    assert metrics.debtor_customers == 5 and metrics.non_debtor_customers == 0
    assert metrics.receivables == Decimal("1190") + 50 + 75 + 10 + 10
    assert metrics.net_balance == metrics.receivables and metrics.advances == 0
    assert {w.ward_name: w.receivables for w in metrics.debt_by_ward} == {
        "Xã 1": Decimal("1240"), "Xã 2": Decimal("95"),
    }
    assert [i.key for i in items] == [A, C]  # debt desc

    last = items[-1]
    _, page2, _, _ = await repo.get_customer_overview(
        FILTERS, 2, CustomerOverviewCursor(last.current_debt, last.revenue, last.label, last.key),
    )
    _, jumped, _, _ = await repo.get_customer_overview(FILTERS, 2, None, offset=2)
    assert [i.key for i in page2] == [i.key for i in jumped] == [B, E]


@pytest.mark.asyncio
async def test_ranking_offset_pages_do_not_overlap_on_ties(repository):
    repo, _ = repository
    first, _ = await repo.get_ranking(FILTERS, RankingDimension.CUSTOMER, 3, 0)
    second, _ = await repo.get_ranking(FILTERS, RankingDimension.CUSTOMER, 3, 3)
    keys = [i.key for i in first + second]
    assert len(keys) == len(set(keys)) == 5


@pytest.mark.asyncio
async def test_list_orders_counts_lines_only_for_the_page(repository):
    repo, _ = repository
    page, total = await repo.list_orders(OrderFilters(date_from=date(2025, 3, 1), date_to=date(2025, 4, 1), customer_id=A), 10, 0)
    assert total == 2
    assert {o.invoice_number: o.line_count for o in page} == {"XB-A1": 2, "XB-A2": 1}
    assert [o.invoice_number for o in page] == ["XB-A2", "XB-A1"]


@pytest.mark.asyncio
async def test_order_ledger_balance_comes_from_the_signed_ledger(repository):
    repo, _ = repository
    data = await repo.get_order_ledger_export(OrderLedgerExportFilters(
        date_from=date(2025, 3, 1), date_to=date(2025, 3, 31), customer_id=A,
    ))
    events = {}
    for item in data.items:
        events.setdefault((item.voucher_number, item.reason), item)
    assert events[("XB-A1", "Xuất bán")].running_debt == Decimal("1300")  # opening 1000 + 300
    assert events[("XB-A1", "Xuất bán")].payment_amount == Decimal("0")
    assert events[("XB-A2", "Xuất bán")].payment_amount == Decimal("40")  # total 100, debt 60
    assert events[("NT-A", "Nhập trả")].running_debt == Decimal("1320")
    assert events[("PT001-0325", "Thu nợ")].running_debt == Decimal("1170")
    # A ledger row without any invoice still moves the balance and is shown.
    assert data.items[-1].voucher_number == "legacy-orphan"
    assert data.items[-1].running_debt == Decimal("1190")

    # Geography filters never reduce an explicit customer's opening balance/receipts.
    narrowed = await repo.get_order_ledger_export(OrderLedgerExportFilters(
        date_from=date(2025, 3, 1), date_to=date(2025, 3, 31), customer_id=A, ward_names=("Không có",),
    ))
    assert narrowed.items[-1].running_debt == Decimal("1190")

    # Without date_from only the typed opening balance seeds the running total.
    full = await repo.get_order_ledger_export(OrderLedgerExportFilters(customer_id=A))
    assert full.items[-1].running_debt == Decimal("1190")


@pytest.mark.asyncio
async def test_customer_debt_export_and_filter_option_escaping(repository):
    repo, connection = repository
    rows = await repo.get_customer_debt_export(CustomerDebtExportFilters())
    assert [r.key for r in rows][:2] == [A, C]
    assert D not in {r.key for r in rows}

    async with AsyncSession(bind=connection) as session:
        session.add(customer(cid(9), "Giảm 100% hàng_lẻ", "Xã 9"))
        session.add(customer(cid(10), "Giảm 1000 hàng", "Xã 9"))
        await session.flush()
    percent = await repo.get_filter_options("100%", 50)
    assert [o.label for o in percent.customers] == ["Giảm 100% hàng_lẻ"]
    underscore = await repo.get_filter_options("hà_g", 50)
    assert underscore.customers == ()
    assert [o.label for o in (await repo.get_filter_options("%", 50)).customers] == ["Giảm 100% hàng_lẻ"]
