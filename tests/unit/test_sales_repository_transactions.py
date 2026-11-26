"""Transaction scope and SQL shape of the sales sync repositories (no database)."""
import pytest
from sqlalchemy.dialects import postgresql

from src.modules.sales.infrastructure.repositories.customer_repository import CustomerRepository
from src.modules.sales.infrastructure.repositories.sales_invoice_repository import (
    SalesInvoiceRepository,
)
from src.modules.sales.infrastructure.repositories.sales_return_repository import (
    SalesReturnRepository,
)
from src.modules.sales.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


class FakeResult:
    def __init__(self, rows=(), rowcount=0, scalar=0):
        self._rows = list(rows)
        self.rowcount = rowcount
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar


class FakeSession:
    def __init__(self, returning_rows=None):
        self.sql: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self._returning_rows = returning_rows or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.closed = True

    async def execute(self, statement):
        text = str(statement.compile(dialect=postgresql.dialect()))
        self.sql.append(text)
        for prefix, rows in self._returning_rows.items():
            if text.startswith(prefix):
                return FakeResult(rows)
        return FakeResult()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class SessionFactory:
    """Hands out a new FakeSession per call, like sessionmaker."""

    def __init__(self, **session_kwargs):
        self.sessions: list[FakeSession] = []
        self._kwargs = session_kwargs

    def __call__(self):
        session = FakeSession(**self._kwargs)
        self.sessions.append(session)
        return session


def return_row(source_id):
    return {
        "source_id": source_id, "return_number": f"NT-{source_id}",
        "returned_at": None, "customer_id": "c1", "customer_name_snapshot": "A",
        "customer_address_detail_snapshot": None, "customer_village_name_snapshot": None,
        "customer_ward_name_snapshot": None, "return_total_amount": 1,
    }


def return_line(source_id, line_id):
    return {
        "source_id": source_id, "source_line_id": line_id, "line_number": 1,
        "product_name": "gạch", "product_category_name": None, "unit_name": "viên",
        "unit_price": 1, "quantity": 1, "line_amount": 1,
    }


@pytest.mark.asyncio
async def test_return_sync_soft_deletes_lines_of_stale_returns_with_array_binding():
    factory = SessionFactory(returning_rows={"INSERT INTO sales_returns": [("S1", "r1")]})
    repository = SalesReturnRepository(factory)

    await repository.sync_snapshot([return_row("S1")], [return_line("S1", "L1")])

    statements = factory.sessions[0].sql
    line_update = next(
        i for i, s in enumerate(statements) if s.startswith("UPDATE sales_return_lines")
    )
    return_update = next(
        i for i, s in enumerate(statements) if s.startswith("UPDATE sales_returns")
    )
    assert line_update < return_update, "lines of stale returns are retired first"
    assert "sales_return_lines.return_id IN (SELECT sales_returns.return_id" in statements[line_update]
    for statement in (statements[line_update], statements[return_update]):
        assert "!= ALL" in statement or "<> ALL" in statement
        assert "NOT IN" not in statement
    assert factory.sessions[0].commits == 1


@pytest.mark.asyncio
async def test_empty_return_snapshot_still_retires_every_return_and_its_lines():
    factory = SessionFactory()
    repository = SalesReturnRepository(factory)

    result = await repository.sync_snapshot([], [])

    assert result == {"returns": 0, "lines": 0}
    statements = factory.sessions[0].sql
    assert any(s.startswith("UPDATE sales_return_lines") for s in statements)
    assert any(s.startswith("UPDATE sales_returns") for s in statements)


@pytest.mark.asyncio
async def test_repositories_commit_per_call_outside_a_transaction():
    factory = SessionFactory()

    await CustomerRepository(factory).soft_delete_unreferenced()
    await SalesInvoiceRepository(factory).soft_delete_missing(["PX-1"])

    assert [s.commits for s in factory.sessions] == [1, 1]
    assert all(s.closed for s in factory.sessions)


@pytest.mark.asyncio
async def test_unit_of_work_shares_one_session_and_commits_once():
    factory = SessionFactory()
    unit_of_work = SqlAlchemyUnitOfWork(factory)
    customers = CustomerRepository(factory)
    invoices = SalesInvoiceRepository(factory)
    returns = SalesReturnRepository(factory)

    async with unit_of_work.transaction():
        await customers.soft_delete_unreferenced()
        await invoices.soft_delete_missing(["PX-1"])
        await returns.sync_snapshot([], [])
        assert await invoices.count_active() == 0

    assert len(factory.sessions) == 1
    session = factory.sessions[0]
    assert session.commits == 1 and session.rollbacks == 0 and session.closed
    assert len(session.sql) >= 5


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_every_write_on_failure():
    factory = SessionFactory()
    unit_of_work = SqlAlchemyUnitOfWork(factory)
    invoices = SalesInvoiceRepository(factory)

    with pytest.raises(RuntimeError, match="boom"):
        async with unit_of_work.transaction():
            await invoices.soft_delete_missing(["PX-1"])
            raise RuntimeError("boom")

    session = factory.sessions[0]
    assert session.commits == 0 and session.rollbacks == 1 and session.closed
    # The shared session must not leak into later standalone calls.
    await invoices.soft_delete_missing(["PX-2"])
    assert len(factory.sessions) == 2 and factory.sessions[1].commits == 1


@pytest.mark.asyncio
async def test_nested_transaction_joins_the_outer_one():
    factory = SessionFactory()
    unit_of_work = SqlAlchemyUnitOfWork(factory)

    async with unit_of_work.transaction():
        async with unit_of_work.transaction():
            await SalesInvoiceRepository(factory).soft_delete_missing([])
        assert factory.sessions[0].commits == 0

    assert len(factory.sessions) == 1 and factory.sessions[0].commits == 1


@pytest.mark.asyncio
async def test_customer_upsert_keeps_existing_address_when_source_has_none():
    factory = SessionFactory(returning_rows={"INSERT INTO customers": [("k", "id-1")]})

    ids = await CustomerRepository(factory).upsert_many([{
        "customer_identity_key": "k", "customer_name": "A", "address_detail": None,
        "village_name": None, "ward_name": None,
    }])

    assert ids == {"k": "id-1"}
    statement = factory.sessions[0].sql[0].lower()
    assert "coalesce(excluded.address_detail, customers.address_detail)" in statement
