"""LLM-generated SQL runs under the read-only `sales_sql_reader` role."""
import importlib.util
from pathlib import Path

import asyncpg
import pytest

from config.settings import DatabaseSettings
from src.modules.assistant.application.services.sql_service import ALLOWED_SQL_TABLES
from src.modules.assistant.domain.errors import SQLDatabaseFailureError, SQLValidationError
from src.modules.assistant.infrastructure.database.postgres_sql_executor import PostgresSQLExecutor
from tests.unit.test_sql_executor_and_analyzer_hardening import (
    adapted_error,
    make_engine,
    make_stream_result,
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _granted_tables() -> set[str]:
    granted: set[str] = set()
    for path in MIGRATIONS.glob("*.py"):
        if "SQL_READER_TABLES" not in path.read_text(encoding="utf-8"):
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        granted.update(module.SQL_READER_TABLES)
    return granted


def test_reader_role_is_granted_exactly_the_allowed_tables():
    # A table added to ALLOWED_SQL_TABLES needs a migration granting SELECT on it,
    # otherwise generated SQL on that table fails with permission denied.
    assert _granted_tables() == set(ALLOWED_SQL_TABLES)


@pytest.mark.asyncio
async def test_executor_switches_to_reader_role_inside_read_only_transaction():
    engine, statements = make_engine(result=make_stream_result([], ["n"]))

    await PostgresSQLExecutor(engine, reader_role="sales_sql_reader").execute_sql("SELECT 1")

    assert statements[0] == "SET TRANSACTION READ ONLY"
    assert statements[1] == 'SET LOCAL ROLE "sales_sql_reader"'
    assert statements[-1] == "SELECT 1"


@pytest.mark.asyncio
async def test_missing_reader_role_is_an_infrastructure_failure_not_a_query_defect():
    missing = adapted_error(asyncpg.exceptions.UndefinedObjectError('role "x" does not exist'))
    engine, statements = make_engine(set_error=missing)

    with pytest.raises(SQLDatabaseFailureError) as caught:
        await PostgresSQLExecutor(engine, reader_role="sales_sql_reader").execute_sql("SELECT 1")

    # The LLM repair loop only retries SQLValidationError; a role problem must not reach it.
    assert not isinstance(caught.value, SQLValidationError)
    assert "SELECT 1" not in statements


@pytest.mark.parametrize("role", ["Sales", "x; DROP TABLE users", "a-b", "1abc"])
def test_reader_role_must_be_a_plain_identifier(role):
    with pytest.raises(ValueError):
        PostgresSQLExecutor(object(), reader_role=role)
    with pytest.raises(ValueError):
        DatabaseSettings(sql_reader_role=role)


@pytest.mark.parametrize("value", [None, "", "  "])
def test_blank_reader_role_disables_the_switch(value):
    assert DatabaseSettings(sql_reader_role=value).sql_reader_role is None
    assert PostgresSQLExecutor(object(), reader_role=value)._reader_role is None


def test_reader_role_defaults_to_migration_role():
    assert DatabaseSettings().sql_reader_role == "sales_sql_reader"
