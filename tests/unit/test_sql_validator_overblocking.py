"""Regressions where the SQL validator blocked legitimate read-only queries.

Production logs showed a plan rejected for JSON_AGG() whose repair then failed with
"bảng ngoài phạm vi: tong" (a CTE the repair dropped). The validator now says what
to change, and the repair loop sees its own previous attempt.
"""
from unittest.mock import AsyncMock

import pytest

from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.schema_linker import SchemaLinker
from src.modules.assistant.application.services.sql_service import SQLQueryPlan, SQLService
from src.modules.assistant.application.use_cases.text_to_sql_use_case import TextToSQLUseCase
from src.modules.assistant.domain.errors import (
    SQLFunctionNotAllowedError,
    SQLKeywordForbiddenError,
    SQLTableNotAllowedError,
    SQLUndefinedRelationError,
)

T = "customer_debt_transactions"


def validate(sql: str) -> str:
    return SQLService(llm_service=None).validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # Keywords inside string literals are data.
        "SELECT l.product_name FROM sales_invoice_lines l WHERE l.product_name ILIKE '%Giấy copy%'",
        "SELECT c.customer_name FROM customers c WHERE c.customer_name ILIKE '%Update%'",
        "SELECT c.customer_name FROM customers c WHERE c.customer_name = 'pg_test'",
        "SELECT c.customer_name FROM customers c WHERE c.customer_name = 'Call Center'",
        # Harmless text/array/date functions.
        "SELECT REPLACE(c.customer_name, 'a', 'b') AS ten FROM customers c",
        "SELECT regexp_replace(c.customer_name, '\\s+', ' ', 'g') AS ten FROM customers c",
        "SELECT array_to_string(ARRAY_AGG(c.customer_name), ', ') AS ds FROM customers c",
        "SELECT date_bin(INTERVAL '7 days', d.occurred_at, TIMESTAMP '2025-01-01') AS tuan "
        f"FROM {T} d",
        # Total repeated on each detail row instead of JSON_AGG.
        f"WITH thu AS (SELECT d.source_id, d.amount FROM {T} d WHERE d.source_type = 'receipt'), "
        "tong AS (SELECT SUM(amount) AS tong_thu FROM thu) "
        "SELECT thu.source_id, thu.amount, tong.tong_thu FROM thu CROSS JOIN tong",
    ],
)
def test_legitimate_queries_pass(sql):
    validate(sql)


def test_json_functions_get_an_actionable_message():
    with pytest.raises(SQLFunctionNotAllowedError) as caught:
        validate(f"WITH thu AS (SELECT d.amount FROM {T} d) SELECT JSON_AGG(thu.amount) AS ct FROM thu")
    assert isinstance(caught.value, SQLKeywordForbiddenError)
    assert "JSON_AGG()" in caught.value.message
    assert "bảng phẳng" in caught.value.message


def test_undefined_cte_is_reported_as_missing_cte():
    with pytest.raises(SQLUndefinedRelationError) as caught:
        validate(f"WITH thu AS (SELECT d.amount FROM {T} d) SELECT tong.s FROM thu CROSS JOIN tong")
    assert isinstance(caught.value, SQLTableNotAllowedError)
    assert '"tong"' in caught.value.message and "CTE" in caught.value.message
    assert "customer_debt_transactions" in caught.value.message


def test_restricted_table_keeps_the_scope_message():
    with pytest.raises(SQLTableNotAllowedError) as caught:
        validate("SELECT u.email FROM users u")
    assert not isinstance(caught.value, SQLUndefinedRelationError)


def test_quote_inside_double_quoted_identifier_cannot_hide_a_keyword():
    # A plain regex over '...' would treat `'b", 1 AS delete, '` as one literal.
    with pytest.raises(SQLKeywordForbiddenError):
        validate('SELECT c.customer_name AS "a\'b", 1 AS delete, \'c\' AS d FROM customers c')


@pytest.mark.asyncio
async def test_validator_rejection_gets_a_second_repair_that_sees_the_first_attempt():
    executor = AsyncMock()
    executor.execute_sql.return_value = ([(1,)], ["so_phieu"])
    service = AsyncMock()
    first = f"SELECT JSON_AGG(d.amount) AS ct FROM {T} d"
    dropped_cte = f"WITH thu AS (SELECT d.amount FROM {T} d) SELECT tong.s FROM thu CROSS JOIN tong"
    fixed = f"SELECT COUNT(d.source_id) AS so_phieu FROM {T} d"
    service.generate.return_value = [SQLQueryPlan("thu_no_ky_va_chi_tiet", first)]
    service.validate_all = SQLService(None).validate_all
    service.validate = SQLService(None).validate
    service.draft_repair.side_effect = [
        SQLQueryPlan("thu_no_ky_va_chi_tiet", dropped_cte),
        SQLQueryPlan("thu_no_ky_va_chi_tiet", fixed),
    ]

    queries, _, ok, has_data, code = await TextToSQLUseCase(
        executor, SchemaLinker(), service
    ).execute(QueryAnalyzer().analyze("Thu nợ tháng này và chi tiết"))

    assert ok and has_data and code is None
    assert queries == [SQLService(None).validate(fixed)]
    second_plan, second_error = service.draft_repair.await_args_list[1].args[:2]
    assert second_plan.sql == dropped_cte
    assert "CTE" in second_error
