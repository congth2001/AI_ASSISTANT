"""Opt-in PostgreSQL tests of the sales sync against real SQL, in a rolled-back transaction.

Tables are created in ``pg_temp`` from the ORM metadata inside one outer
transaction that is always rolled back, and every repository session joins it
through a SAVEPOINT. No public table is read or written.

Run with AI_SALES_TEST_DSN (or AI_ANALYTICS_TEST_DSN) for a dedicated database,
or AI_ANALYTICS_LOCAL_DB_TEST=1 for the configured local PostgreSQL.
"""
import os
from contextlib import asynccontextmanager
from decimal import Decimal

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.config_manager import get_database_settings
from src.common.infrastructure.database.base import Base
from src.modules.sales.application.use_cases.sync_business_data_use_case import (
    SyncBusinessDataUseCase,
)
from src.modules.sales.domain.errors import EmptySnapshotError, SnapshotShrinkError
from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtTransaction,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)
from src.modules.sales.infrastructure.repositories.customer_debt_transaction_repository import (
    CustomerDebtTransactionRepository,
)
from src.modules.sales.infrastructure.repositories.customer_repository import CustomerRepository
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

SALES_TABLES = [
    Customer.__table__, SalesInvoice.__table__, SalesInvoiceLine.__table__,
    SalesReturn.__table__, SalesReturnLine.__table__, CustomerDebtTransaction.__table__,
]


def _dsn() -> str:
    dsn = os.getenv("AI_SALES_TEST_DSN") or os.getenv("AI_ANALYTICS_TEST_DSN")
    if dsn:
        return dsn
    if os.getenv("AI_ANALYTICS_LOCAL_DB_TEST") == "1":
        return get_database_settings().sqlalchemy_url
    pytest.skip("Set AI_SALES_TEST_DSN, AI_ANALYTICS_TEST_DSN or AI_ANALYTICS_LOCAL_DB_TEST=1")


@pytest_asyncio.fixture
async def world():
    engine = create_async_engine(_dsn(), echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            await connection.execute(text("SET LOCAL search_path TO pg_temp"))
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=SALES_TABLES)
            )

            @asynccontextmanager
            async def factory_cm():
                session = AsyncSession(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                )
                try:
                    yield session
                finally:
                    await session.close()

            class Factory:
                def __call__(self):
                    return factory_cm()

            factory = Factory()
            repositories = {
                "customers": CustomerRepository(factory),
                "invoices": SalesInvoiceRepository(factory),
                "lines": SalesInvoiceLineRepository(factory),
                "debts": CustomerDebtTransactionRepository(factory),
                "returns": SalesReturnRepository(factory),
            }
            use_case = SyncBusinessDataUseCase(
                repositories["customers"], repositories["invoices"], repositories["lines"],
                repositories["debts"], repositories["returns"],
                unit_of_work=SqlAlchemyUnitOfWork(factory),
            )

            async def scalar(statement):
                async with factory() as session:
                    return (await session.execute(statement)).scalar_one()

            yield use_case, scalar
            await outer.rollback()
    finally:
        await engine.dispose()


def invoices(numbers):
    return pd.DataFrame(
        [
            {
                "issued_at": "2025-03-01 08:00:00", "invoice_number": number,
                "customer_name": "Anh An", "address_detail": "Nhà 1", "village_name": "Xóm 1",
                "ward_name": "Xã A", "invoice_total_amount": 100.005, "debt_delta_amount": 0,
            }
            for number in numbers
        ],
        columns=["issued_at", "invoice_number", "customer_name", "address_detail", "village_name",
                 "ward_name", "invoice_total_amount", "debt_delta_amount"],
    )


def goods(numbers):
    return pd.DataFrame(
        [
            {
                "invoice_number": number, "product_name": "gạch", "product_category_name": "Gạch",
                "unit_name": "Viên", "unit_price": 10, "quantity": 2.5, "line_amount": 25,
            }
            for number in numbers
        ],
        columns=["invoice_number", "product_name", "product_category_name", "unit_name",
                 "unit_price", "quantity", "line_amount"],
    )


def debts(ids):
    return pd.DataFrame(
        [
            {"source_type": "sale", "source_id": i, "occurred_at": "2025-03-01",
             "customer_name": "Anh An", "address_detail": None, "village_name": "Xóm 1",
             "ward_name": "Xã A", "amount": 10}
            for i in ids
        ],
        columns=["source_type", "source_id", "occurred_at", "customer_name", "address_detail",
                 "village_name", "ward_name", "amount"],
    )


def returns(ids):
    return pd.DataFrame(
        [
            {"source_id": i, "return_number": f"NT-{i}", "occurred_at": "2025-03-02",
             "return_total_amount": 25, "customer_name": "Anh An", "address_detail": None,
             "village_name": "Xóm 1", "ward_name": "Xã A"}
            for i in ids
        ],
        columns=["source_id", "return_number", "occurred_at", "return_total_amount",
                 "customer_name", "address_detail", "village_name", "ward_name"],
    )


def return_lines(ids):
    return pd.DataFrame(
        [
            {"source_id": i, "source_line_id": f"L-{i}", "product_name": "gạch",
             "product_category_name": "Gạch", "unit_name": "Viên", "unit_price": 10,
             "quantity": 2.5, "line_amount": 25}
            for i in ids
        ],
        columns=["source_id", "source_line_id", "product_name", "product_category_name",
                 "unit_name", "unit_price", "quantity", "line_amount"],
    )


def count(model, *, active=True):
    statement = select(func.count()).select_from(model)
    if active:
        statement = statement.where(model.deleted_at.is_(None))
    return statement


async def full_sync(use_case, numbers, return_ids, **kwargs):
    return await use_case.sync_all(
        invoices(numbers), goods(numbers), debts([f"d{n}" for n in numbers]),
        returns(return_ids), return_lines(return_ids), **kwargs,
    )


@pytest.mark.asyncio
async def test_full_sync_is_idempotent_and_rounds_money(world):
    use_case, scalar = world

    first = await full_sync(use_case, ["PX-1", "PX-2"], ["1", "2"])
    second = await full_sync(use_case, ["PX-1", "PX-2"], ["1", "2"])

    assert first == second
    assert await scalar(count(SalesInvoice)) == 2
    assert await scalar(count(SalesInvoiceLine)) == 2
    assert await scalar(count(SalesReturn)) == 2
    assert await scalar(count(SalesReturnLine)) == 2
    assert await scalar(count(CustomerDebtTransaction)) == 2
    assert await scalar(count(Customer)) == 1
    total = await scalar(select(SalesInvoice.invoice_total_amount).where(SalesInvoice.invoice_number == "PX-1"))
    assert total == Decimal("100.01")
    quantity = await scalar(select(func.max(SalesInvoiceLine.quantity)))
    assert quantity == Decimal("2.500")


@pytest.mark.asyncio
async def test_stale_returns_retire_their_lines_too(world):
    use_case, scalar = world
    await full_sync(use_case, ["PX-1"], ["1", "2", "3", "4"])

    await full_sync(use_case, ["PX-1"], ["1", "2", "3"])  # -25%: within guard threshold

    assert await scalar(count(SalesReturn)) == 3
    assert await scalar(count(SalesReturnLine)) == 3
    assert await scalar(count(SalesReturnLine, active=False)) == 4
    orphans = await scalar(
        select(func.count())
        .select_from(SalesReturnLine)
        .join(SalesReturn, SalesReturn.return_id == SalesReturnLine.return_id)
        .where(SalesReturnLine.deleted_at.is_(None), SalesReturn.deleted_at.is_not(None))
    )
    assert orphans == 0


@pytest.mark.asyncio
async def test_guard_blocks_empty_and_shrunken_snapshots_and_keeps_data(world):
    use_case, scalar = world
    numbers = [f"PX-{i}" for i in range(10)]
    await full_sync(use_case, numbers, ["1"])

    with pytest.raises(EmptySnapshotError):
        await full_sync(use_case, [], ["1"])
    with pytest.raises(SnapshotShrinkError):
        await full_sync(use_case, numbers[:5], ["1"])

    assert await scalar(count(SalesInvoice)) == 10

    await full_sync(use_case, [], ["1"], allow_shrink=True)
    assert await scalar(count(SalesInvoice)) == 0


@pytest.mark.asyncio
async def test_failure_midway_rolls_back_all_earlier_writes(world):
    use_case, scalar = world
    await full_sync(use_case, ["PX-1"], ["1"])
    bad_returns = returns(["1"])
    bad_returns["return_total_amount"] = -5  # violates ck_sales_returns_total_nonnegative

    with pytest.raises(Exception):
        await use_case.sync_all(
            invoices(["PX-1", "PX-NEW"]), goods(["PX-1", "PX-NEW"]), debts(["dPX-1", "dNEW"]),
            bad_returns, return_lines(["1"]),
        )

    assert await scalar(count(SalesInvoice)) == 1  # PX-NEW was written, then rolled back
    assert await scalar(count(CustomerDebtTransaction)) == 1
