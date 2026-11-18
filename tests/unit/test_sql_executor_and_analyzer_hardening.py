"""PostgresSQLExecutor error translation/limits and QueryAnalyzer reload locking."""
import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.exc import DBAPIError

from src.common.errors import ExternalServiceError, OperationTimeoutError
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.domain.errors import SQLValidationError
from src.modules.assistant.infrastructure.database.postgres_sql_executor import (
    PostgresSQLExecutor,
)


def adapted_error(driver_error: Exception) -> DBAPIError:
    """Build the DBAPIError SQLAlchemy raises for an asyncpg exception."""
    mapping = AsyncAdapt_asyncpg_dbapi(asyncpg)._asyncpg_error_translate
    for klass in type(driver_error).__mro__:
        if klass in mapping:
            translated = mapping[klass](f"{type(driver_error)}: {driver_error}")
            translated.pgcode = translated.sqlstate = driver_error.sqlstate
            translated.__cause__ = driver_error
            return DBAPIError("SELECT 1", {}, translated)
    raise AssertionError("unmapped error")


def make_engine(result=None, error: Exception | None = None):
    statements: list[str] = []
    conn = MagicMock()

    async def execute(statement):
        text = str(statement)
        statements.append(text)
        if error is not None and not text.startswith("SET"):
            raise error
        return result

    conn.execute = execute

    @asynccontextmanager
    async def begin():
        yield

    conn.begin = begin

    @asynccontextmanager
    async def connect():
        yield conn

    engine = MagicMock()
    engine.connect = connect
    return engine, statements


@pytest.mark.asyncio
async def test_executor_sets_timeouts_and_reads_at_most_max_rows():
    result = MagicMock()
    result.fetchmany.return_value = [(1,)]
    result.keys.return_value = ["n"]
    engine, statements = make_engine(result=result)

    rows, cols = await PostgresSQLExecutor(engine).execute_sql("SELECT 1")

    assert (rows, cols) == ([(1,)], ["n"])
    result.fetchmany.assert_called_once_with(PostgresSQLExecutor.MAX_ROWS)
    result.fetchall.assert_not_called()
    joined = "\n".join(statements)
    assert "SET TRANSACTION READ ONLY" in statements[0]
    for setting in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout"):
        assert f"SET LOCAL {setting}" in joined


@pytest.mark.asyncio
async def test_executor_reports_query_defect_with_sanitized_message():
    driver_error = asyncpg.exceptions.UndefinedColumnError('column "bad" does not exist')
    engine, _ = make_engine(error=adapted_error(driver_error))

    with pytest.raises(SQLValidationError) as caught:
        await PostgresSQLExecutor(engine).execute_sql("SELECT bad FROM customers")

    assert 'column "bad" does not exist' in caught.value.message
    assert "42703" in caught.value.message
    assert "SELECT" not in caught.value.message


@pytest.mark.asyncio
async def test_executor_maps_timeout_and_infrastructure_errors():
    timeout = adapted_error(asyncpg.exceptions.QueryCanceledError("canceling statement"))
    engine, _ = make_engine(error=timeout)
    with pytest.raises(OperationTimeoutError):
        await PostgresSQLExecutor(engine).execute_sql("SELECT 1")

    shutdown = adapted_error(asyncpg.exceptions.AdminShutdownError("terminating connection"))
    engine, _ = make_engine(error=shutdown)
    with pytest.raises(ExternalServiceError) as caught:
        await PostgresSQLExecutor(engine).execute_sql("SELECT 1")
    assert "terminating" not in caught.value.message


@pytest.mark.asyncio
async def test_concurrent_ensure_fresh_reloads_once(caplog):
    customer_repo, good_repo = MagicMock(), MagicMock()

    async def slow_list(limit):
        await asyncio.sleep(0.05)
        return [{"customer_name": "Anh Minh"}]

    customer_repo.list = AsyncMock(side_effect=slow_list)
    good_repo.list_categories = AsyncMock(return_value=["Gạch"])
    analyzer = QueryAnalyzer(customer_repo, good_repo)

    await asyncio.gather(*(analyzer.ensure_fresh() for _ in range(5)))

    assert customer_repo.list.await_count == 1
    assert analyzer.customer_names == ["Anh Minh"]


@pytest.mark.asyncio
async def test_customer_load_limit_is_logged(caplog, monkeypatch):
    monkeypatch.setattr(QueryAnalyzer, "CUSTOMER_LOAD_LIMIT", 2)
    customer_repo, good_repo = MagicMock(), MagicMock()
    customer_repo.list = AsyncMock(
        return_value=[{"customer_name": "A B"}, {"customer_name": "C D"}]
    )
    good_repo.list_categories = AsyncMock(return_value=[])

    with caplog.at_level(logging.WARNING):
        await QueryAnalyzer(customer_repo, good_repo).ensure_fresh()

    assert any("load limit" in r.getMessage() for r in caplog.records)
