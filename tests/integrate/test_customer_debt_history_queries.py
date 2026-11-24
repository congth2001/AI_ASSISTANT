"""Opt-in PostgreSQL tests of the customer debt-history queries, in a rolled-back transaction.

Data is loaded through the real sales sync (twice, so the second run audits a
retroactive edit), then read through ``DashboardAnalyticsRepository``. Tables live in
``pg_temp`` inside one outer transaction that is always rolled back.

Run with AI_SALES_TEST_DSN / AI_ANALYTICS_TEST_DSN, or AI_ANALYTICS_LOCAL_DB_TEST=1.
"""
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.config_manager import get_database_settings
from src.common.infrastructure.database.base import Base
from src.modules.analytics.application.use_cases.customer_debt_history_use_case import (
    CustomerDebtHistoryUseCase,
)
from src.modules.analytics.domain.models.customer_debt_history import (
    DebtHistoryEntryFilters,
    DebtHistoryFilters,
    DebtRevisionFilters,
)
from src.modules.analytics.domain.models.order_ledger import OrderLedgerExportFilters
from src.modules.analytics.infrastructure.repositories.dashboard_analytics_repository import (
    DashboardAnalyticsRepository,
)
from src.modules.sales.application.use_cases.sync_business_data_use_case import (
    SyncBusinessDataUseCase,
)
from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtRevision,
    CustomerDebtTransaction,
    CustomerDebtTransactionChange,
    EtlSyncRun,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)
from src.modules.sales.infrastructure.repositories.customer_debt_transaction_repository import (
    CustomerDebtTransactionRepository,
)
from src.modules.sales.infrastructure.repositories.customer_repository import CustomerRepository
from src.modules.sales.infrastructure.repositories.debt_revision_repository import (
    DebtRevisionRepository,
)
from src.modules.sales.infrastructure.repositories.sales_invoice_line_repository import (
    SalesInvoiceLineRepository,
)
from src.modules.sales.infrastructure.repositories.sales_invoice_repository import (
    SalesInvoiceRepository,
)
from src.modules.sales.infrastructure.repositories.sales_return_repository import (
    SalesReturnRepository,
)
from src.modules.sales.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

D = Decimal
TABLES = [
    Customer.__table__, SalesInvoice.__table__, SalesInvoiceLine.__table__,
    SalesReturn.__table__, SalesReturnLine.__table__, CustomerDebtTransaction.__table__,
    EtlSyncRun.__table__, CustomerDebtTransactionChange.__table__, CustomerDebtRevision.__table__,
]


def _dsn() -> str:
    dsn = os.getenv("AI_SALES_TEST_DSN") or os.getenv("AI_ANALYTICS_TEST_DSN")
    if dsn:
        return dsn
    if os.getenv("AI_ANALYTICS_LOCAL_DB_TEST") == "1":
        return get_database_settings().sqlalchemy_url
    pytest.skip("Set AI_SALES_TEST_DSN, AI_ANALYTICS_TEST_DSN or AI_ANALYTICS_LOCAL_DB_TEST=1")


PROFILE = {"customer_name": "Anh An", "address_detail": "Nhà 1", "village_name": "Xóm 1", "ward_name": "Xã A"}


def invoices():
    return pd.DataFrame([{
        "issued_at": "2025-03-01 08:00:00", "invoice_number": "XB-1", **PROFILE,
        "invoice_total_amount": 150, "debt_delta_amount": 100,
    }])


def goods():
    return pd.DataFrame([{
        "invoice_number": "XB-1", "product_name": "gạch", "product_category_name": "Gạch",
        "unit_name": "Viên", "unit_price": 10, "quantity": 15, "line_amount": 150,
    }])


def debts(sale_amount):
    rows = [
        ("opening", "O1", "2025-01-01 00:00", 50),
        ("sale", "D1", "2025-03-01 08:00", sale_amount),
        ("receipt", "R1", "2025-03-05 08:00", -40),
        ("receipt", "R2", "2025-03-05 08:00", -5),     # same timestamp: keyset tie
        ("sales_return", "T1", "2025-03-06 09:00", -25),
    ]
    return pd.DataFrame([
        {"source_type": kind, "source_id": source_id, "occurred_at": when, **PROFILE, "amount": amount}
        for kind, source_id, when, amount in rows
    ])


def returns():
    return pd.DataFrame([{
        "source_id": "T1", "return_number": "NT-1", "occurred_at": "2025-03-06 09:00",
        "return_total_amount": 25, **PROFILE,
    }])


def return_lines():
    return pd.DataFrame([{
        "source_id": "T1", "source_line_id": "L1", "product_name": "gạch",
        "product_category_name": "Gạch", "unit_name": "Viên", "unit_price": 10,
        "quantity": 2.5, "line_amount": 25,
    }])


@pytest_asyncio.fixture
async def world():
    engine = create_async_engine(_dsn(), echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            await connection.execute(text("SET LOCAL search_path TO pg_temp"))
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))

            @asynccontextmanager
            async def session_cm():
                session = AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
                )
                try:
                    yield session
                finally:
                    await session.close()

            class Factory:
                def __call__(self):
                    return session_cm()

            factory = Factory()
            sync = SyncBusinessDataUseCase(
                CustomerRepository(factory), SalesInvoiceRepository(factory),
                SalesInvoiceLineRepository(factory), CustomerDebtTransactionRepository(factory),
                SalesReturnRepository(factory), unit_of_work=SqlAlchemyUnitOfWork(factory),
                debt_revision_repository=DebtRevisionRepository(factory),
            )
            for sale_amount in (100, 120):  # second run: retroactive +20 on D1
                await sync.sync_all(invoices(), goods(), debts(sale_amount), returns(), return_lines())
            async with factory() as session:
                customer_id = str((await session.execute(select(Customer.customer_id))).scalar_one())
            yield DashboardAnalyticsRepository(factory), customer_id
            await outer.rollback()
    finally:
        await engine.dispose()


async def all_entries(repository, customer_id, filters=DebtHistoryEntryFilters(), limit=1):
    """Walk every page; returns (entries, number of pages)."""
    collected, cursor, pages = [], None, 0
    while True:
        rows, has_more = await repository.list_entry_page(customer_id, filters, cursor, limit)
        pages += 1
        collected.extend(entry for entry, _ in rows)
        if not has_more:
            return collected, pages
        cursor = rows[-1][1]


@pytest.mark.asyncio
async def test_entries_carry_whole_ledger_balance_vouchers_and_revision_flag(world):
    repository, customer_id = world

    entries, pages = await all_entries(repository, customer_id, limit=2)

    assert pages == 3
    assert [(e.source_id, e.voucher_number, e.balance_after) for e in entries] == [
        ("T1", "NT-1", D("100.00")),
        ("R2", "R2-0325", D("125.00")),
        ("R1", "R1-0325", D("130.00")),
        ("D1", "XB-1", D("170.00")),
        ("O1", "O1", D("50.00")),
    ]
    by_source = {e.source_id: e for e in entries}
    assert by_source["D1"].invoice_id and by_source["D1"].return_id is None
    assert by_source["T1"].return_id and by_source["T1"].invoice_id is None
    assert by_source["D1"].revised and by_source["D1"].last_revised_at is not None
    assert not by_source["R1"].revised


@pytest.mark.asyncio
async def test_keyset_pages_of_one_never_skip_or_repeat_tied_rows(world):
    repository, customer_id = world

    entries, pages = await all_entries(repository, customer_id, limit=1)

    assert pages == 5
    assert [e.source_id for e in entries] == ["T1", "R2", "R1", "D1", "O1"]


@pytest.mark.asyncio
async def test_range_and_type_filters_keep_the_running_balance(world):
    repository, customer_id = world

    in_range, _ = await all_entries(
        repository, customer_id,
        DebtHistoryEntryFilters(date_from=date(2025, 3, 2), date_to=date(2025, 3, 5)), limit=50,
    )
    assert [(e.source_id, e.balance_after) for e in in_range] == [("R2", D("125.00")), ("R1", D("130.00"))]
    sales, _ = await all_entries(
        repository, customer_id, DebtHistoryEntryFilters(source_types=("sale",)), limit=50
    )
    assert [(e.source_id, e.balance_after) for e in sales] == [("D1", D("170.00"))]


@pytest.mark.asyncio
async def test_history_matches_the_order_ledger_export(world):
    repository, customer_id = world

    history = await CustomerDebtHistoryUseCase(repository).get_history(
        customer_id, DebtHistoryFilters(date_from=date(2025, 3, 1), date_to=date(2025, 3, 31))
    )
    export = await repository.get_order_ledger_export(OrderLedgerExportFilters(customer_id=customer_id))

    s = history.summary
    assert s.opening_balance == D("50.00") and s.closing_balance == D("100.00")
    assert (s.increase_amount, s.receipt_amount, s.return_amount) == (D("120.00"), D("45.00"), D("25.00"))
    assert s.current_balance == D("100.00")
    assert s.revision_count == 1 and s.last_revision_delta == D("20.00")
    assert export.items[-1].running_debt == s.closing_balance
    assert history.customer.customer_name == "Anh An"


@pytest.mark.asyncio
async def test_customer_and_system_revision_lists(world):
    repository, customer_id = world

    revisions, has_more = await repository.list_customer_revisions(customer_id, None, 20, 50)
    assert not has_more
    (revision,) = revisions
    assert (revision.balance_before, revision.balance_after, revision.balance_delta) == (
        D("80.00"), D("100.00"), D("20.00"))
    assert revision.earliest_affected_at == datetime(2025, 3, 1, 8)
    (change,) = revision.changes
    assert (change.change_type, change.voucher_number, change.old_amount, change.new_amount) == (
        "updated", "XB-1", D("100.00"), D("120.00"))

    latest, items, has_more = await repository.list_debt_revisions(DebtRevisionFilters(), None, 25)
    assert latest.revised_customers == 1 and latest.retroactive_delta == D("20.00")
    assert not latest.is_baseline
    assert [(i.customer_name, i.balance_delta) for i in items] == [("Anh An", D("20.00"))]
    _, other_ward, _ = await repository.list_debt_revisions(
        DebtRevisionFilters(ward_names=("Xã B",)), None, 25
    )
    assert other_ward == []
    assert (await repository.get_customer_profile("00000000-0000-4000-8000-000000000000")) is None
